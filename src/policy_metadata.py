"""Explicit match-length metadata; never infer rules from later replay events."""
from copy import deepcopy
import re


THRONE_ROUND_COUNTS = {15: 1, 16: 2}
_GAME_ID = re.compile(r"\d{6}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
TENHOU_GAME_ID = re.compile(r"\d{10}gm-(00b1|00b9|00f1|00f9)-0000-[0-9a-f]{8}\Z")
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
    if metadata.get("sourcePlatform") == "tenhou":
        return _validate_tenhou_metadata(metadata, game_id, source_sha256)
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


def _validate_tenhou_metadata(metadata, game_id, source_sha256):
    """Tenhou GO values describe rules, never Mahjong Soul room IDs."""
    identifier = metadata.get("gameId")
    match = TENHOU_GAME_ID.fullmatch(identifier) if isinstance(identifier, str) else None
    if not match:
        raise ValueError("Invalid Tenhou match metadata game ID")
    if game_id is not None and identifier != game_id:
        raise ValueError("Match metadata game ID differs")
    go_type = int(match[1], 16)
    if (type(metadata.get("schemaVersion")) is not int or metadata["schemaVersion"] != 1 or
            type(metadata.get("playerCount")) is not int or metadata["playerCount"] != 3 or
            type(metadata.get("goType")) is not int or metadata["goType"] != go_type or
            type(metadata.get("roundCount")) is not int or
            metadata["roundCount"] != (2 if go_type & 8 else 1) or "modeId" in metadata):
        raise ValueError("Unsupported or inconsistent Tenhou match rules")
    source_hash = metadata.get("sourceCompressedSha256")
    if not isinstance(source_hash, str) or not _SHA256.fullmatch(source_hash):
        raise ValueError("Missing match metadata source hash")
    if source_sha256 is not None and source_hash != source_sha256:
        raise ValueError("Match metadata source hash differs")
    provenance = metadata.get("provenance")
    if (not isinstance(provenance, dict) or provenance.get("kind") != "tenhou-xml-header" or
            not isinstance(provenance.get("archive"), str) or not provenance["archive"] or
            not isinstance(provenance.get("xmlSha256"), str) or
            not _SHA256.fullmatch(provenance["xmlSha256"])):
        raise ValueError("Missing Tenhou XML provenance")
    return deepcopy(metadata)
