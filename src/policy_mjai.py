"""MJAI -> visible policy samples with explicitly reconstructed operation masks.

RiichiEnv supplies legal actions, not labels. We infer pass only when play
advances to the next normal draw; competing claims are censored. Its 0.4.10
event API does not reconstruct kan-response windows, so the rest of a hand
after a kan is excluded, including potential missed-ron state after that kan.
"""
from collections import Counter
import json

from riichienv import ActionType, GameRule, RiichiEnv
from riichienv.convert import tid_to_mpsz

from policy_actions import action_key, legal_actions
from policy_features import RULESET, encode_state, tile34
from policy_mjai_state import MjaiVisibleState, tile_name


ENGINE_VERSION = "0.4.10"
RESOLVERS = {"tsumo", "dahai", "chi", "pon", "daiminkan", "ankan", "kakan", "hora", "ryukyoku"}
KAN = {"ankan", "kakan", "daiminkan"}


def _tile(value):
    # RiichiEnv uses mpsz 0 for a red five, matching the application.
    return tid_to_mpsz(value)


def operation_details(env, seat, observation, public):
    """Build an operation mask from rules alone, before looking at the label."""
    offered = {}
    discards = set()
    for action in observation.legal_actions():
        value = json.loads(action.to_mjai())
        kind = value["type"]
        if kind == "none":
            continue
        if kind == "dahai":
            offered.setdefault(1, set())
            discards.add(tile_name(value["pai"]))
        elif kind == "reach":
            # Riichi is a combined declare-and-discard action in our policy.
            # The clone is advanced with the declaration, never the actual tile.
            copy = env.clone()
            copy.apply_event({"type": "reach", "actor": seat})
            values = [json.loads(a.to_mjai()) for a in copy.get_observation(seat).legal_actions()]
            offered[7] = {tile_name(a["pai"]) for a in values if a["type"] == "dahai"}
        elif kind in ("chi", "pon", "daiminkan", "ankan", "kakan"):
            tiles = [tile_name(t) for t in value["consumed"]]
            if kind == "kakan":
                tiles.append(tile_name(value["pai"]))
            code = {"chi": 2, "pon": 3, "ankan": 4, "daiminkan": 5, "kakan": 6}[kind]
            offered.setdefault(code, set()).add("|".join(sorted(tiles)))
        elif kind == "hora":
            offered[8 if action.action_type == ActionType.TSUMO else 9] = set()
        elif kind == "ryukyoku":
            if public.state["noCallsYet"] and not public.state["rivers"][seat]:
                offered[10] = set()
        else:
            raise ValueError(f"unsupported rule-engine action {kind}")
    if 1 in offered:
        # Riichi lock is encoded separately by the existing action adapter.
        if not public.state["riichi"][seat] and not public.state["riichiPending"][seat]:
            allowed = {t.replace("0", "5") for t in discards}
            offered[1] = {_tile(t) for t in observation.hand if _tile(t).replace("0", "5") not in allowed}
    return [{"type": code, "combination": sorted(values)} for code, values in sorted(offered.items())]


def _observed(window, event, riichi=False):
    state, kind = window["state"], event["type"]
    actor = state["selfSeat"]
    if kind == "ryukyoku":
        return next((a for a in window["candidates"] if a["action"] == "abort"), None)
    if event.get("actor") != actor:
        return None
    if kind == "dahai":
        return {"action": "riichi" if riichi else "discard", "tile": tile_name(event["pai"]),
                "consumed": [], "moqie": bool(event.get("tsumogiri")) and state["lastAction"]["name"] != "ActionNewRound"}
    if kind in ("chi", "pon", "daiminkan"):
        tile = tile_name(event["pai"])
        return {"action": kind, "tile": tile, "calledTile": tile, "fromSeat": event["target"],
                "consumed": [tile_name(t) for t in event["consumed"]]}
    if kind == "ankan":
        tiles = [tile_name(t) for t in event["consumed"]]
        return {"action": "ankan", "tile": tiles[0].replace("0", "5"), "consumed": tiles}
    if kind == "kakan":
        tile = tile_name(event["pai"])
        indices = [i for i, meld in enumerate(state["melds"][actor])
                   if meld["type"] == 1 and tile34(meld["tiles"][0]) == tile34(tile)]
        if len(indices) != 1:
            raise ValueError("added kan lacks a unique public pon")
        return {"action": "shouminkan", "tile": tile, "consumed": [tile], "meldIndex": indices[0]}
    if kind == "hora":
        if event["target"] == actor:
            return {"action": "tsumo", "consumed": []}
        tile = state["lastAction"]["tile"]
        return {"action": "ron", "tile": tile, "calledTile": tile,
                "fromSeat": event["target"], "consumed": []}
    return None


def extract_game(events, game_id):
    """Return samples and exclusions; every emitted label matches a frozen mask."""
    if not events or events[0].get("type") != "start_game" or events[-1].get("type") != "end_game":
        raise ValueError("expected a complete MJAI game")
    if len(events[0].get("names", [])) != 4:
        raise ValueError("MJAI conversion currently supports four-player games only")
    env = RiichiEnv(game_mode="4p-red-half", rule=GameRule.default_mjsoul())
    public = MjaiVisibleState()
    temporary, permanent = [False] * 4, [False] * 4
    pending, samples, excluded = {}, [], Counter()
    rounds, blocked, declared = -1, False, None
    audit = {"gameId": game_id, "sourceFormat": "mjai", "operationSource": "riichienv-reconstructed",
             "engineVersion": ENGINE_VERSION, "officialOperationLists": False}

    def emit(window, action, label_source):
        if action is None:
            excluded["unresolved_action"] += 1
            return
        key = action_key(action)
        if key not in window["keys"]:
            excluded["label_not_in_reconstructed_mask"] += 1
            return
        samples.append({"schemaVersion": 1, "ruleset": RULESET, "gameId": game_id,
                        "roundId": str(rounds), "decisionId": window["id"],
                        "seat": window["state"]["selfSeat"], "state": window["state"],
                        "action": action, "labelSource": label_source,
                        "sourceFormat": "mjai", "operationSource": "riichienv-reconstructed",
                        "engineVersion": ENGINE_VERSION})

    for index, event in enumerate(events):
        kind = event["type"]
        if kind == "start_kyoku":
            if pending:
                excluded["unfinished_window"] += len(pending)
            pending.clear()
            rounds += 1
            blocked, declared = False, None
            temporary, permanent = [False] * 4, [False] * 4
        elif kind == "reach":
            if event["actor"] not in pending:
                excluded["declaration_without_window"] += 1
            declared = event["actor"]
        elif kind in RESOLVERS and pending:
            winners = {}
            if kind == "hora":
                for following in events[index:]:
                    if following["type"] != "hora":
                        break
                    winners[following["actor"]] = following
            for seat, window in pending.items():
                state = window["state"]
                last = state["lastAction"]
                response = last["name"] == "ActionDiscardTile" and last["seat"] != seat
                actual = _observed(window, winners.get(seat, event), declared == seat)
                if seat in winners or (event.get("actor") == seat and kind != "tsumo"):
                    emit(window, actual, "accepted")
                elif kind == "ryukyoku" and not response:
                    emit(window, actual, "accepted")
                elif response and kind == "tsumo" and event["actor"] == (last["seat"] + 1) % 4:
                    emit(window, {"action": "pass", "consumed": []}, "inferred_pass")
                else:
                    excluded["censored_response" if response else "unresolved_self_action"] += 1
                # Ron outranks calls. Absence of a win before a call/draw proves
                # missed ron, but does NOT prove a lower-priority pass label.
                if response and seat not in winners and kind in ("tsumo", "chi", "pon", "daiminkan"):
                    if any(a["action"] == "ron" for a in window["candidates"]):
                        temporary[seat] = True
                        permanent[seat] |= bool(state["riichi"][seat] or state["riichiPending"][seat])
            pending.clear()
            if kind == "dahai":
                declared = None
        if kind == "tsumo":
            temporary[event["actor"]] = False
        if kind in KAN:
            blocked = True
            excluded["hand_suffix_after_kan"] += 1
        if kind in ("end_kyoku", "end_game"):
            excluded["unfinished_window"] += len(pending)
            pending.clear()
        env.missed_agari_doujun = [a or b for a, b in zip(temporary, permanent)]
        env.apply_event(event)
        env.missed_agari_doujun = [a or b for a, b in zip(temporary, permanent)]
        public.apply(event, index)
        if blocked or kind not in ("tsumo", "dahai", "chi", "pon"):
            continue
        seats = [event["actor"]] if kind != "dahai" else [s for s in range(4) if s != event["actor"]]
        for seat in seats:
            observation = env.get_observation(seat)
            details = operation_details(env, seat, observation, public)
            if not details:
                continue
            hand = [_tile(t) for t in observation.hand]
            discarded = {tile34(d["tile"]) for d in public.state["rivers"][seat]}
            furiten = temporary[seat] or permanent[seat] or bool(discarded.intersection(observation.waits))
            state = public.snapshot(seat, hand, details, furiten)
            try:
                candidates = legal_actions(state)
                encode_state(state)
            except (ValueError, KeyError, TypeError, IndexError) as error:
                excluded["invalid_visible_window:" + str(error)] += 1
                continue
            if candidates:
                pending[seat] = {"state": state, "candidates": candidates,
                                 "keys": {action_key(a) for a in candidates},
                                 "id": f"{game_id}:{rounds}:{index}:{seat}"}
    audit.update({"rounds": rounds + 1, "samples": len(samples), "excluded": dict(excluded),
                  "actions": dict(Counter(s["action"]["action"] for s in samples)),
                  "labelSources": dict(Counter(s["labelSource"] for s in samples))})
    return samples, audit
