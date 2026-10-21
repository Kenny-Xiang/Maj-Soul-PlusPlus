#!/usr/bin/env python3
"""Measure both policy slots on the offline live-wire scenarios, without opening the App."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def benchmark(paths, repeats):
    import numpy as np
    from advice_worker import AdviceWorker
    from monitor import overlay_update
    from policy_model import PolicyAdvisor
    from test_policy_live_windows import wire_cases

    run = subprocess.run([shutil.which("node"), str(ROOT / "tests/helpers/policy_live_windows.cjs")],
                         input=json.dumps(wire_cases()), text=True, capture_output=True, timeout=30, check=True)
    flows = json.loads(run.stdout)
    advisor = PolicyAdvisor(paths)
    report = {"createdAt": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "python": platform.python_version(), "repeats": repeats,
              "scope": "Synthetic ActionPrototype wire frames through real browser/core; real model weights and AdviceWorker; no WebKit or network latency.",
              "nativeTimerIntervalMs": 50, "nativeTimerIncluded": False, "models": {}, "modes": {}}
    for players, model in advisor.models.items():
        report["models"][str(players)] = {"path": str(Path(paths[players]).resolve()), "sha256": model.sha256,
                                         "playerCount": model.metadata["playerCount"], "purpose": model.metadata["purpose"]}
    worker = AdviceWorker(advisor)

    def summary(values):
        return {"count": len(values), "medianMs": float(np.median(values)),
                "p95Ms": float(np.percentile(values, 95)), "maxMs": max(values)}

    try:
        for players in (3, 4):
            windows = [(flow["name"], turn) for flow in flows for turn in flow["turns"]
                       if turn["state"]["playerCount"] == players and turn["state"]["canAct"]]
            metrics = {name: [] for name in ("inference", "workerQueue", "workerCalculate", "workerDeliveryWait",
                                            "workerTotal", "nativeScriptBuild", "callerTotal")}
            for _, turn in windows:
                result = advisor(turn["state"])
                if result["status"] != "ready":
                    raise ValueError(f"{players}p model must produce ready advice: {result}")
            for repeat in range(repeats):
                for name, turn in windows:
                    state = turn["state"]
                    started = time.perf_counter()
                    result = advisor(state)
                    metrics["inference"].append((time.perf_counter() - started) * 1000)
                    started = time.perf_counter()
                    key = f'{players}:{repeat}:{name}:{state["lastStep"]}'
                    worker.submit(key, state)
                    with worker.condition:
                        if not worker.condition.wait_for(lambda: worker.completed is not None, 5):
                            raise TimeoutError(f"inference exceeded five seconds: {key}")
                    packet = worker.take_result()
                    if packet["adviceKey"] != key or packet["advice"]["status"] != "ready":
                        raise ValueError(f"unexpected worker response: {packet}")
                    diagnostics = packet["diagnostics"]
                    for name_, source in (("workerQueue", "queueMs"), ("workerCalculate", "calculateWallMs"),
                                          ("workerDeliveryWait", "deliveryWaitMs"), ("workerTotal", "totalMs")):
                        metrics[name_].append(diagnostics[source])
                    script_started = time.perf_counter()
                    overlay_update(packet)
                    metrics["nativeScriptBuild"].append((time.perf_counter() - script_started) * 1000)
                    metrics["callerTotal"].append((time.perf_counter() - started) * 1000)
                    worker.take_diagnostics()
            report["modes"][str(players)] = {"windowsPerRepeat": len(windows),
                "windows": [{"scenario": name, "step": turn["state"]["lastStep"], "trigger": turn["trigger"],
                             "operations": turn["state"]["operations"]} for name, turn in windows],
                "metrics": {name: summary(values) for name, values in metrics.items()}}
    finally:
        worker.close()
        worker.thread.join(5)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--three-player", type=Path, required=True)
    parser.add_argument("--four-player", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if not shutil.which("node"):
        parser.error("Node is required for the live-wire collector")
    report = benchmark({3: args.three_player, 4: args.four_player}, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(args.output), "metrics": {mode: value["metrics"]
                      for mode, value in report["modes"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
