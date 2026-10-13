"""Offline acceptance of the real policy weights inside a frozen application."""
import hashlib
import json
import math
from pathlib import Path

from policy_actions import ACTION_TYPES, action_key, legal_actions
from policy_bundle import resolve_models
from policy_model import PolicyAdvisor


def verify_policy(resource_root, fixture_path):
    resource_root = Path(resource_root)
    paths = resolve_models(resource_root, {})  # Deliberately ignore environment overrides.
    if set(paths) != {3, 4}:
        raise ValueError("policy verification requires both bundled player slots")
    manifest = json.loads((resource_root / "policy-models/manifest.json").read_text())
    advisor = PolicyAdvisor(paths)
    payload = Path(fixture_path).read_bytes()
    fixture = json.loads(payload)
    if fixture.get("schemaVersion") != 1:
        raise ValueError("unsupported policy verification fixture")
    modes = {}
    for players, model in advisor.models.items():
        if (model.metadata["purpose"] != "behavior-cloning" or
                model.sha256 != manifest["models"][str(players)]["sha256"]):
            raise ValueError(f"{players}-player bundled model is not the expected behavior-cloning model")
        modes[str(players)] = {"sha256": model.sha256, "readyWindows": 0, "waitingWindows": 0}
    seen = set()
    for window in fixture["windows"]:
        state = window["state"]
        mode = modes[str(state["playerCount"])]
        result = advisor(state)
        if not state["canAct"]:
            if (result["status"], result["candidates"], result["best"]) != ("waiting", [], None):
                raise ValueError(f"{window['scenario']}: closed window produced advice")
            mode["waitingWindows"] += 1
            continue
        expected = {item["actionId"]: item for item in legal_actions(state)}
        actual = result["candidates"]
        if (result["status"] != "ready" or result.get("modelSha256") != mode["sha256"] or
                len(actual) != len(expected) or {item["actionId"] for item in actual} != set(expected) or
                not actual or result["best"] != actual[0]):
            raise ValueError(f"{window['scenario']}: model routing or legal candidate mismatch")
        for item in actual:
            if (action_key(item) != item["actionId"] or
                    {key: value for key, value in item.items() if key != "policyProbability"} != expected[item["actionId"]]):
                raise ValueError(f"{window['scenario']}: candidate action parameters changed")
        probabilities = [item["policyProbability"] for item in actual]
        if (any(not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities) or
                not math.isclose(sum(probabilities), 1., rel_tol=1e-5, abs_tol=1e-6) or
                probabilities != sorted(probabilities, reverse=True)):
            raise ValueError(f"{window['scenario']}: invalid action probabilities")
        seen.update(item["action"] for item in actual)
        mode["readyWindows"] += 1
    if seen != set(ACTION_TYPES) or any(not mode["readyWindows"] or not mode["waitingWindows"] for mode in modes.values()):
        raise ValueError("policy verification did not cover all actions and both open/closed player windows")
    return {"status": "ok", "models": modes, "windows": len(fixture["windows"]),
            "actionTypes": sorted(seen), "fixtureSha256": hashlib.sha256(payload).hexdigest()}
