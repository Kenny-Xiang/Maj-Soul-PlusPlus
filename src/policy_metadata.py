"""Explicit match-length metadata; never infer rules from later replay events."""
from copy import deepcopy
import re


THRONE_ROUND_COUNTS = {15: 1, 16: 2}
_GAME_ID = re.compile(r"\d{6}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def validate_match_metadata(metadata, game_id=None, source_sha256=None):
    """Validate the narrow official-header sidecar contract and return a copy.

    File-backed provenance is verified by scripts/policy_match_metadata.py.
    Missing metadata stays unknown, including when the replay reaches South.
    """
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise ValueError("Match metadata must be an object")
    identifier, mode = metadata.get("gameId"), metadata.get("modeId")
    if not isinstance(identifier, str) or not _GAME_ID.fullmatch(identifier):
        raise ValueError("Invalid match metadata game ID")
    if game_id is not None and identifier != game_id:
        raise ValueError("Match metadata game ID differs")
    if (type(metadata.get("schemaVersion")) is not int or metadata["schemaVersion"] != 1 or
            type(metadata.get("playerCount")) is not int or metadata["playerCount"] != 4 or
            type(mode) is not int or mode not in THRONE_ROUND_COUNTS or
            type(metadata.get("roundCount")) is not int or
            metadata["roundCount"] != THRONE_ROUND_COUNTS[mode]):
        raise ValueError("Unsupported or inconsistent match metadata rules")
    source_hash = metadata.get("sourceCompressedSha256")
    if not isinstance(source_hash, str) or not _SHA256.fullmatch(source_hash):
        raise ValueError("Missing match metadata source hash")
    if source_sha256 is not None and source_hash != source_sha256:
        raise ValueError("Match metadata source hash differs")
    provenance = metadata.get("provenance")
    if (not isinstance(provenance, dict) or provenance.get("kind") != "official-header-config" or
            not isinstance(provenance.get("archive"), str) or not provenance["archive"]):
        raise ValueError("Missing official match metadata provenance")
    for name in ("headSha256", "responseSha256", "schemaSha256"):
        value = provenance.get(name)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError(f"Missing match metadata {name}")
    return deepcopy(metadata)
