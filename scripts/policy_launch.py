#!/usr/bin/env python3
"""Validate explicit policy model slots and launch the source macOS application."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from zipfile import BadZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def existing_instance_running():
    import fcntl
    from monitor import DATA

    try:
        lock = (DATA / "monitor.lock").open("rb")
    except FileNotFoundError:
        return False
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
    return False


def prepare(models, environ=None):
    from policy_model import PolicyModel

    if not models:
        raise ValueError("provide --four-player and/or --three-player")
    dependencies = {name: importlib.util.find_spec(name) is not None
                    for name in ("numpy", "objc", "Foundation", "AppKit", "WebKit")}
    missing = [name for name, present in dependencies.items() if not present]
    if missing:
        raise ValueError("missing source-app dependencies: " + ", ".join(missing) +
                         "; install requirements-build.txt and requirements-policy.txt")
    if sys.platform != "darwin":
        raise ValueError("the source application requires macOS")
    environment = dict(os.environ if environ is None else environ)
    for players in (3, 4):
        environment.pop(f"MAJSOUL_POLICY_MODEL_{players}P", None)
    summaries = []
    for players, path in sorted(models.items()):
        path = Path(path).expanduser().resolve()
        model = PolicyModel(path)
        if model.metadata["playerCount"] != players:
            raise ValueError(f"{path}: model playerCount does not match the {players}-player slot")
        environment[f"MAJSOUL_POLICY_MODEL_{players}P"] = str(path)
        summaries.append({"path": str(path), "sha256": model.sha256,
                          **{key: model.metadata[key] for key in
                             ("format", "playerCount", "purpose", "featureSignature", "actionVersion")}})
    return {"python": sys.executable, "dependencies": dependencies, "models": summaries,
            "existingInstanceRunning": existing_instance_running(),
            "automaticPlay": "off at startup"}, environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--four-player", type=Path, help="four-player NPZ model")
    parser.add_argument("--three-player", type=Path, help="three-player NPZ model")
    parser.add_argument("--check", action="store_true", help="print validation results without opening the application")
    args = parser.parse_args(argv)
    models = {players: path for players, path in ((4, args.four_player), (3, args.three_player)) if path}
    try:
        report, environment = prepare(models)
    except (ImportError, OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not args.check:
        if report["existingInstanceRunning"]:
            parser.error("Maj-Soul++ is already running; quit it before launching with model paths. "
                         "The existing instance cannot load these new environment variables.")
        os.execve(sys.executable, [sys.executable, str(ROOT / "src/monitor.py")], environment)


if __name__ == "__main__":
    main()
