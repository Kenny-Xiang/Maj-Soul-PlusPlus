"""Versioned, actor-visible features shared by training and NumPy inference.

The snapshot baseline deliberately summarizes river order; full event history is
kept by the replay importer for a later sequence-model comparison. No outcome,
account identity, hidden hand, wall, or opponent operation field is read here.
"""
from collections import Counter
import hashlib
import json

import numpy as np


FEATURE_VERSION = 2
RULESET = "majsoul-standard-v1"
TILES = tuple(f"{n}{s}" for s in "mps" for n in range(1, 10)) + tuple(f"{n}z" for n in range(1, 8))
TILES37 = TILES + ("0m", "0p", "0s")
TILE_IDS = {tile: i for i, tile in enumerate(TILES37)}
ACTIONS = ("discard", "riichi", "chi", "pon", "daiminkan", "ankan",
           "shouminkan", "kita", "tsumo", "ron", "abort", "pass")
EVENTS = ("ActionNewRound", "ActionDealTile", "ActionDiscardTile",
          "ActionChiPengGang", "ActionAnGangAddGang", "ActionBaBei")
PLANE_NAMES = ("hand>=1", "hand>=2", "hand>=3", "hand>=4", "hand_red",
               "draw", "draw_red", "dora_indicators/4", "visible/4", "unseen/4") + tuple(
    f"seat{seat}:{name}" for seat in range(4) for name in (
        "river_count/4", "river_red", "river_tsumogiri/4", "river_latest_index/length",
        "riichi_discard", "last_discard", "chi_tiles/4", "pon_tiles/4",
        "open_kan_tiles/4", "closed_kan_tiles/4", "meld_red"))
GLOBAL_NAMES = tuple(f"seat{seat}:{name}" for seat in range(4) for name in (
    "exists", "score/100000", "score_diff/100000", "riichi", "riichi_pending",
    "double_riichi", "north/4", "dealer")) + (
    "players3", "players4", "round_wind/3", "honba/10", "sticks/10", "left/70",
    "can_discard", "furiten", "furiten_known",
    "self_wind/3", "no_calls_yet", "can_double_riichi") + tuple(f"last_actor{seat}" for seat in range(4)) + EVENTS
ACTION_NAMES = ACTIONS + tuple(f"tile:{t}" for t in TILES37) + tuple(
    f"called:{t}" for t in TILES37) + tuple(f"consumed/4:{t}" for t in TILES37) + tuple(
    f"source{seat}" for seat in range(4)) + tuple(f"meld{i}" for i in range(4)) + (
    "origin_unknown", "hand_discard", "draw_discard")
FEATURE_SIGNATURE = hashlib.sha256(json.dumps({
    "version": FEATURE_VERSION, "ruleset": RULESET, "planes": PLANE_NAMES,
    "globals": GLOBAL_NAMES, "actions": ACTION_NAMES,
}, sort_keys=True).encode()).hexdigest()


def tile34(tile):
    index = TILE_IDS[tile]
    return index if index < 34 else (4, 13, 22)[index - 34]


def _counts(tiles):
    result = np.zeros(34, dtype=np.float32)
    for tile in tiles:
        result[tile34(tile)] += 1
    return result


def encode_state(state):
    """Encode only the decision maker's current, complete public snapshot."""
    players, own = state["playerCount"], state["selfSeat"]
    if players not in (3, 4) or type(own) is not int or own not in range(players):
        raise ValueError("invalid player count or seat")
    if not state.get("handComplete") or not state.get("historyComplete") or state.get("recovery"):
        raise ValueError("policy requires a complete visible-state baseline")
    hand = state["hand"]
    rivers, melds = state["rivers"], state["melds"]
    if len(rivers) < players or len(melds) < players or len(state["scores"]) < players:
        raise ValueError("missing player data")
    planes = np.zeros((len(PLANE_NAMES), 34), dtype=np.float32)
    counts = _counts(hand)
    for i in range(4):
        planes[i] = counts > i
    for tile in hand:
        if tile.startswith("0"):
            planes[4, tile34(tile)] += 1
    draw = state.get("lastDraw")
    if draw is not None and (state.get("lastAction") or {}).get("name") != "ActionNewRound":
        if draw not in hand:
            raise ValueError("draw is not in own hand")
        planes[5, tile34(draw)] = 1
        planes[6, tile34(draw)] = float(draw.startswith("0"))
    planes[7] = _counts(state["doras"]) / 4
    known = list(hand) + list(state["doras"])
    for seat in range(players):
        known.extend(d["tile"] for d in rivers[seat] if not d.get("called"))
        known.extend(t for meld in melds[seat] for t in meld["tiles"])
        known.extend(["4z"] * state["north"][seat])
    physical = np.full(34, 4, dtype=np.float32)
    if players == 3:
        physical[1:8] = 0
    visible = _counts(known)
    if np.any(visible > physical):
        raise ValueError("visible tiles exceed physical inventory")
    planes[8], planes[9] = visible / 4, (physical - visible) / 4
    scalars = []
    round_ = state["round"]
    for relative in range(4):
        if relative >= players:
            scalars.extend([0.] * 8)
            continue
        seat = (own + relative) % players
        base = 10 + relative * 11
        river = rivers[seat]
        for i, entry in enumerate(river):
            tile = entry["tile"]
            at = tile34(tile)
            planes[base, at] += .25
            planes[base + 1, at] += float(tile.startswith("0"))
            planes[base + 2, at] += .25 * bool(entry.get("moqie"))
            planes[base + 3, at] = (i + 1) / len(river)
            planes[base + 4, at] = max(planes[base + 4, at], float(bool(entry.get("riichi"))))
        if river:
            planes[base + 5, tile34(river[-1]["tile"])] = 1
        for meld in melds[seat]:
            kind = meld["type"]
            if kind not in (0, 1, 2, 3):
                raise ValueError("unknown meld type")
            planes[base + 6 + kind] += _counts(meld["tiles"]) / 4
            for tile in meld["tiles"]:
                if tile.startswith("0"):
                    planes[base + 10, tile34(tile)] += 1
        scalars.extend([1, state["scores"][seat] / 100000,
                        (state["scores"][seat] - state["scores"][own]) / 100000,
                        float(bool(state["riichi"][seat])),
                        float(bool(state.get("riichiPending", [False] * 4)[seat])),
                        float(bool(state.get("doubleRiichi", [False] * 4)[seat])),
                        state["north"][seat] / 4, float(seat == round_["ju"])])
    furiten = state.get("furiten")
    scalars.extend([float(players == 3), float(players == 4), round_["chang"] / 3,
                    round_["ben"] / 10, state["riichiSticks"] / 10, state["left"] / 70,
                    float(bool(state["canDiscard"])), float(bool(furiten)), float(furiten is not None),
                    ((own - round_["ju"]) % players) / 3,
                    float(bool(state.get("noCallsYet"))), float(bool(state.get("canDoubleRiichi")))])
    last = state.get("lastAction") or {}
    scalars.extend(float(last.get("seat") == (own + relative) % players and relative < players)
                   for relative in range(4))
    scalars.extend(float(last.get("name") == name) for name in EVENTS)
    scalars = np.asarray(scalars, dtype=np.float32)
    if scalars.shape != (len(GLOBAL_NAMES),) or not np.isfinite(scalars).all():
        raise ValueError("invalid public scalars")
    return planes, scalars


def encode_actions(state, actions):
    """A shared scorer sees semantic candidates, never server list positions."""
    result = np.zeros((len(actions), len(ACTION_NAMES)), dtype=np.float32)
    for i, action in enumerate(actions):
        result[i, ACTIONS.index(action["action"])] = 1
        offset = len(ACTIONS)
        for key in ("tile", "calledTile"):
            if action.get(key) is not None:
                result[i, offset + TILE_IDS[action[key]]] = 1
            offset += 37
        for tile, count in Counter(action.get("consumed", [])).items():
            result[i, offset + TILE_IDS[tile]] = count / 4
        offset += 37
        if action.get("fromSeat") is not None:
            relative = (action["fromSeat"] - state["selfSeat"]) % state["playerCount"]
            result[i, offset + relative] = 1
        offset += 4
        if action.get("meldIndex") is not None:
            index = action["meldIndex"]
            if type(index) is not int or index not in range(4):
                raise ValueError("invalid meld index")
            result[i, offset + index] = 1
        offset += 4
        origin = action.get("moqie")
        if origin is not None and type(origin) is not bool:
            raise ValueError("moqie must be boolean")
        result[i, offset + (0 if origin is None else 2 if origin else 1)] = 1
    return result
