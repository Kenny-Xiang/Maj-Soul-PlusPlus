"""Lossless per-game feature cache, bound to source bytes and encoder code."""
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import zstandard


@lru_cache(maxsize=1)
def encoder_signature():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ("policy_actions.py", "policy_features.py", "policy_training.py", "policy_encoded_cache.py"):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def cache_binding(row, players):
    return {"version": 1, "gameId": row["gameId"], "sha256": row["sha256"],
            "samples": row["samples"], "players": players, "encoderSignature": encoder_signature()}


def cache_path(root, binding):
    key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return Path(root) / key[:2] / (key + ".npz.zst")


def read_cache(path, binding):
    payload = zstandard.ZstdDecompressor().decompress(path.read_bytes())
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        metadata = json.loads(str(archive["metadata"].item()))
        if metadata["binding"] != binding:
            raise ValueError("encoded cache source or encoder binding mismatch")
        planes, globals_, actions, offsets, targets, labels, sources = (
            archive[name] for name in ("planes", "globals", "actions", "offsets", "targets", "labels", "sources"))
    count = binding["samples"]
    if (len(planes) != count or len(globals_) != count or len(targets) != count or
            len(labels) != count or len(sources) != count or len(offsets) != count + 1 or
            offsets[0] != 0 or offsets[-1] != len(actions) or np.any(np.diff(offsets) < 1) or
            np.any(targets < 0) or np.any(targets >= np.diff(offsets))):
        raise ValueError("invalid encoded cache dimensions or targets")
    samples = [{"game": binding["gameId"], "planes": planes[i], "globals": globals_[i],
                "actions": actions[offsets[i]:offsets[i + 1]], "target": int(targets[i]),
                "action": str(labels[i]), "labelSource": str(sources[i])} for i in range(count)]
    return samples, metadata["audit"]


def write_cache(path, binding, samples, audit):
    arrays = {"planes": np.stack([s["planes"] for s in samples]),
              "globals": np.stack([s["globals"] for s in samples]),
              "actions": np.concatenate([s["actions"] for s in samples]),
              "offsets": np.cumsum([0] + [len(s["actions"]) for s in samples]),
              "targets": np.asarray([s["target"] for s in samples], dtype=np.int64),
              "labels": np.asarray([s["action"] for s in samples]),
              "sources": np.asarray([s["labelSource"] for s in samples]),
              "metadata": np.asarray(json.dumps({"binding": binding, "audit": audit}, sort_keys=True))}
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    payload = zstandard.ZstdCompressor(level=3, write_checksum=True).compress(buffer.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".encoded-", delete=False) as handle:
        staged = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)
