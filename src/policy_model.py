"""Small candidate-scoring policy, deployed with NumPy and a non-pickle archive."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from policy_actions import ACTION_SCHEMA_VERSION, legal_actions
from policy_features import (FEATURE_SIGNATURE, FEATURE_VERSION, RULESET,
                             PLANE_NAMES, GLOBAL_NAMES, ACTION_NAMES,
                             encode_state, encode_actions)


MODEL_FORMAT = "majsoul-candidate-cnn-v2"


def weight_shapes(config):
    width, blocks, hidden = (config[k] for k in ("channels", "blocks", "hidden"))
    if (any(type(v) is not int for v in (width, blocks, hidden)) or
            not 1 <= width <= 256 or not 1 <= blocks <= 16 or not 1 <= hidden <= 1024):
        raise ValueError("unsupported policy network size")
    shapes = {"conv.weight": (width, len(PLANE_NAMES), 3), "conv.bias": (width,),
              "state.weight": (hidden, width * 34 + len(GLOBAL_NAMES)), "state.bias": (hidden,),
              "score.0.weight": (hidden, hidden + len(ACTION_NAMES)), "score.0.bias": (hidden,),
              "score.2.weight": (1, hidden), "score.2.bias": (1,)}
    for block in range(blocks):
        for layer in ("conv1", "conv2"):
            shapes[f"blocks.{block}.{layer}.weight"] = (width, width, 3)
            shapes[f"blocks.{block}.{layer}.bias"] = (width,)
    return shapes


def _conv(value, weight, bias):
    padded = np.pad(value, ((0, 0), (0, 0), (1, 1)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, 3, axis=2)
    # Pack once to a matrix; BLAS performs the channel/kernel reduction.
    columns = windows.transpose(0, 2, 1, 3).reshape(-1, weight.shape[1] * 3)
    return (columns @ weight.reshape(weight.shape[0], -1).T + bias).reshape(
        value.shape[0], value.shape[2], weight.shape[0]).transpose(0, 2, 1)


class PolicyModel:
    def __init__(self, path):
        path = Path(path)
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(path, allow_pickle=False) as archive:
            self.metadata = json.loads(str(archive["metadata"].item()))
            meta = self.metadata
            expected = {"format": MODEL_FORMAT, "featureVersion": FEATURE_VERSION,
                        "featureSignature": FEATURE_SIGNATURE,
                        "actionVersion": ACTION_SCHEMA_VERSION, "ruleset": RULESET}
            if any(meta.get(key) != value for key, value in expected.items()):
                raise ValueError("model feature/action/rule version does not match this application")
            if meta.get("playerCount") not in (3, 4):
                raise ValueError("model must be trained for exactly three or four players")
            if meta.get("purpose") not in ("smoke", "behavior-cloning"):
                raise ValueError("model training purpose must be explicit")
            self.config = meta["config"]
            shapes = weight_shapes(self.config)
            if set(archive.files) != set(shapes) | {"metadata"}:
                raise ValueError("model weight keys do not match the network")
            self.weights = {}
            for name, shape in shapes.items():
                value = archive[name]
                if value.shape != shape or value.dtype != np.float32 or not np.isfinite(value).all():
                    raise ValueError(f"invalid model weight: {name}")
                self.weights[name] = value

    def logits(self, planes, globals_, actions):
        """Single snapshot, variable number of already validated candidates."""
        if (planes.shape != (len(PLANE_NAMES), 34) or globals_.shape != (len(GLOBAL_NAMES),) or
                actions.ndim != 2 or actions.shape[1] != len(ACTION_NAMES) or not len(actions)):
            raise ValueError("invalid policy input shape")
        if not all(np.isfinite(value).all() for value in (planes, globals_, actions)):
            raise ValueError("policy input contains non-finite values")
        w = self.weights
        x = np.maximum(_conv(planes[None], w["conv.weight"], w["conv.bias"]), 0)
        for i in range(self.config["blocks"]):
            prefix = f"blocks.{i}."
            residual = np.maximum(_conv(x, w[prefix + "conv1.weight"], w[prefix + "conv1.bias"]), 0)
            x = np.maximum(x + _conv(residual, w[prefix + "conv2.weight"], w[prefix + "conv2.bias"]), 0)
        x = np.concatenate((x.reshape(-1), globals_))
        h = np.maximum(x @ w["state.weight"].T + w["state.bias"], 0)
        combined = np.concatenate((np.broadcast_to(h, (len(actions), len(h))), actions), axis=1)
        scored = np.maximum(combined @ w["score.0.weight"].T + w["score.0.bias"], 0)
        logits = (scored @ w["score.2.weight"].T + w["score.2.bias"]).reshape(-1)
        if not np.isfinite(logits).all():
            raise ValueError("model produced non-finite scores")
        return logits

    def predict(self, state):
        if state["playerCount"] != self.metadata["playerCount"]:
            raise ValueError("model player count does not match this game")
        actions = legal_actions(state)
        if not actions:
            return []
        planes, globals_ = encode_state(state)
        logits = self.logits(planes, globals_, encode_actions(state, actions))
        exp = np.exp(logits - logits.max())
        probabilities = exp / exp.sum()
        order = np.argsort(-probabilities, kind="stable")
        return [{**actions[i], "policyProbability": float(probabilities[i])} for i in order]


class PolicyAdvisor:
    """Worker-compatible adapter. A smoke model can be displayed, not executed."""
    def __init__(self, models):
        self.models = {int(players): PolicyModel(path) for players, path in models.items()}
        if any(players != model.metadata["playerCount"] for players, model in self.models.items()):
            raise ValueError("configured model does not match its three/four-player slot")

    def __call__(self, state):
        started = time.monotonic()
        base = {"kind": "policy", "candidates": [], "best": None,
                "model": MODEL_FORMAT, "probabilityMeaning": "human-action-preference"}
        if state.get("phase") != "playing" or not state.get("canAct"):
            return {**base, "status": "waiting", "message": "等待合法操作窗口"}
        model = self.models.get(state.get("playerCount"))
        if model is None:
            return {**base, "status": "unavailable", "message": "当前玩法没有配置策略模型"}
        try:
            candidates = model.predict(state)
            smoke = model.metadata.get("purpose") == "smoke"
            return {**base, "status": "analysis" if smoke else "ready",
                    "message": "样例训练模型，仅供验证" if smoke else "牌谱策略模型推荐",
                    "candidates": candidates, "best": candidates[0] if candidates else None,
                    "rankedCandidateCount": len(candidates), "modelSha256": model.sha256,
                    "elapsedMs": round((time.monotonic() - started) * 1000, 2),
                    "warnings": ["动作偏好不代表和牌率；模型棋力尚未完成对战验证"]}
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            return {**base, "status": "unavailable", "message": f"策略模型暂停推荐：{exc}"}
