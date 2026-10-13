"""Hash-bound bundled policy slots; importing this module needs no ML runtime."""
import hashlib
import json
from pathlib import Path


BUNDLE_FORMAT = "majsoul-policy-bundle-v1"
MODEL_NAMES = {3: "three-player.npz", 4: "four-player.npz"}


def resolve_models(resource_root, environ):
    paths = {players: Path(environ[f"MAJSOUL_POLICY_MODEL_{players}P"]).expanduser()
             for players in (3, 4) if environ.get(f"MAJSOUL_POLICY_MODEL_{players}P")}
    folder = Path(resource_root) / "policy-models"
    if len(paths) == 2 or not folder.exists():
        return paths
    manifest = json.loads((folder / "manifest.json").read_text())
    if (not isinstance(manifest, dict) or manifest.get("format") != BUNDLE_FORMAT or
            not isinstance(manifest.get("models"), dict) or set(manifest["models"]) != {"3", "4"}):
        raise ValueError("bundled policy manifest must contain separate three/four-player models")
    for players, name in MODEL_NAMES.items():
        if players in paths:
            continue
        entry = manifest["models"][str(players)]
        if not isinstance(entry, dict) or entry.get("file") != name or entry.get("playerCount") != players:
            raise ValueError(f"bundled policy has an invalid {players}-player slot")
        path = folder / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            raise ValueError(f"bundled {players}-player model SHA256 does not match manifest")
        paths[players] = path
    return paths
