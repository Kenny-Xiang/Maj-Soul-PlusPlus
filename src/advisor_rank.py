"""Ranked settlement rules from Mahjong Soul client 0.11.252.w.

Only authenticated, internally consistent ranked-room metadata selects a
profile. This module calculates a known final place, not its probability.
See docs/rank-point-rules.md for evidence and unsupported boundaries.
"""
from math import ceil, isfinite


RULES_VERSION = "majsoul-0.11.252.w-2026-10-06"

# mode_id: (players, winds, room, first-place room bonus, second-place bonus)
_MODES = {
    2: (4, 1, 1, 10, 5), 3: (4, 2, 1, 20, 10),
    5: (4, 1, 2, 20, 10), 6: (4, 2, 2, 40, 20),
    8: (4, 1, 3, 40, 20), 9: (4, 2, 3, 80, 40),
    11: (4, 1, 4, 55, 30), 12: (4, 2, 4, 110, 55),
    15: (4, 1, 6, 60, 30), 16: (4, 2, 6, 120, 60),
    17: (3, 1, 1, 15, 0), 18: (3, 2, 1, 30, 0),
    19: (3, 1, 2, 30, 0), 20: (3, 2, 2, 60, 0),
    21: (3, 1, 3, 55, 0), 22: (3, 2, 3, 105, 0),
    23: (3, 1, 4, 75, 0), 24: (3, 2, 4, 160, 0),
    25: (3, 1, 6, 120, 0), 26: (3, 2, 6, 240, 0),
}
_ROOMS = {1: "铜之间", 2: "银之间", 3: "金之间", 4: "玉之间", 6: "王座间"}
_LIMITS = {1: (101, 203), 2: (201, 303), 3: (301, 403),
           4: (401, 503), 6: (501, 720)}
_RANK_NAMES = {2: "雀士", 3: "雀杰", 4: "雀豪", 5: "雀圣"}
# Last-place penalties, indexed by (rank tier, star). East and South differ.
_FOUR_PENALTIES = {
    201: (10, 20), 202: (20, 40), 203: (30, 60),
    301: (40, 80), 302: (50, 100), 303: (60, 120),
    401: (80, 165), 402: (90, 180), 403: (100, 195),
    501: (110, 210), 502: (120, 225), 503: (130, 240),
}
_THREE_PENALTIES = {
    **_FOUR_PENALTIES,
    402: (95, 190), 403: (110, 215),
    501: (125, 240), 502: (140, 265), 503: (160, 290),
}


def _rank_code(level_id, players):
    if type(level_id) is not int:
        return None
    prefix = 10000 if players == 4 else 20000
    code = level_id - prefix
    return code if code in _FOUR_PENALTIES or 701 <= code <= 720 else None


def profile_for_match(match, player_count):
    """Return verified settlement constants, or None when context is unknown.

    Novice and historical 10601/20601 profiles are deliberately unsupported.
    The modern Celestial all-player multiplier needs the complete rank list.
    """
    if not isinstance(match, dict) or type(player_count) is not int:
        return None
    if match.get("source") != "auth-game" or type(match.get("category")) is not int or match["category"] != 2:
        return None
    mode_id = match.get("modeId")
    if type(mode_id) is not int or mode_id not in _MODES:
        return None
    players, winds, room, first, second = _MODES[mode_id]
    for field, expected in (("playerCount", players), ("roundCount", winds), ("room", room)):
        if type(match.get(field)) is not int or match[field] != expected:
            return None
    if player_count != players:
        return None
    code = _rank_code(match.get("levelId"), players)
    low, high = _LIMITS[room]
    if code is None or not low <= code <= high:
        return None
    profile = {"roomName": _ROOMS[room], "playerCount": players,
               "roundCount": winds, "version": RULES_VERSION}
    if code >= 701:
        levels = match.get("levelIds")
        if not isinstance(levels, list) or len(levels) != players or match["levelId"] not in levels:
            return None
        codes = [_rank_code(level, players) for level in levels]
        if any(rank is None or not low <= rank <= high for rank in codes):
            return None
        multiplier = 2 if all(rank >= 701 for rank in codes) else 1
        points = ((30, 10, -10, -30) if winds == 1 else (50, 20, -20, -50)) if players == 4 else (
            (30, 0, -30) if winds == 1 else (50, 0, -50))
        profile.update(rankName=f"魂天Lv{code - 700}", unit="soul",
                       placementPoints=[value * multiplier / 100 for value in points],
                       scoreOrigin=None, scoreDivisor=None)
    else:
        penalties = _FOUR_PENALTIES if players == 4 else _THREE_PENALTIES
        penalty = penalties[code][winds - 1]
        points = [first + 15, second + 5, -5, -penalty - 15] if players == 4 else [first + 15, 0, -penalty - 15]
        profile.update(rankName=f"{_RANK_NAMES[code // 100]}{code % 100}星", unit="pt",
                       placementPoints=points, scoreOrigin=25000 if players == 4 else 35000,
                       scoreDivisor=1000)
    return profile


def settlement_points(profile, score, place):
    """Calculate a known final place (one-based), before promotion/demotion.

    The caller resolves tied scores and distributes final riichi deposits.
    This does not clamp a rank balance or simulate promotion/demotion resets.
    """
    if type(place) is not int or not 1 <= place <= profile["playerCount"]:
        raise ValueError("place must be a one-based final placement")
    points = profile["placementPoints"][place - 1]
    if profile["scoreDivisor"] is None:
        return points
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not isfinite(score):
        raise ValueError("score must be a finite final score")
    return points + ceil((score - profile["scoreOrigin"]) / profile["scoreDivisor"])
