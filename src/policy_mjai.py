"""MJAI -> visible policy samples with explicitly reconstructed operation masks.

RiichiEnv supplies legal actions, not labels. We infer pass only when play
advances to the next normal draw; competing claims are censored. Its 0.4.10
event API does not reconstruct rob-kan windows. Only accepted open kans with
an observed replacement draw are resumed; closed/added kans and fourth-kan
suffixes stay excluded.
"""
from collections import Counter
import json

from riichienv import ActionType, GameRule, RiichiEnv
from riichienv.convert import tid_to_mpsz

from policy_actions import action_key, legal_actions
from policy_features import RULESET, encode_state, tile34
from policy_metadata import validate_match_metadata
from policy_mjai_state import MjaiVisibleState, tile_name


ENGINE_VERSION = "0.4.10"
RESOLVERS = {"tsumo", "dahai", "chi", "pon", "daiminkan", "ankan", "kakan", "kita", "hora", "ryukyoku"}
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
        elif kind == "kita":
            offered[11] = set()
        elif kind == "ryukyoku":
            if public.state["noCallsYet"] and not public.state["rivers"][seat]:
                offered[10] = set()
        else:
            raise ValueError(f"unsupported rule-engine action {kind}")
    if public.state["riichi"][seat] or public.state["riichiPending"][seat]:
        # Mahjong Soul auto-discards a locked draw. Only optional operations
        # open a server decision, where cancelling them is PASS, not discard.
        offered.pop(1, None)
    if 1 in offered:
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
        if (not state["canDiscard"] and state["lastAction"]["name"] == "ActionDealTile"
                and event.get("tsumogiri") is True and tile_name(event["pai"]) == state["lastDraw"]):
            return {"action": "pass", "consumed": []}
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
    if kind == "kita":
        # Plain MJAI does not identify which of two Norths was extracted.
        # Our Tenhou importer preserves the physical tile comparison in XML.
        moqie = event.get("_tenhou", {}).get("tsumogiri")
        if type(moqie) is not bool:
            return None
        return {"action": "kita", "tile": "4z", "consumed": ["4z"],
                "moqie": moqie and state["lastAction"]["name"] != "ActionNewRound"}
    if kind == "hora":
        if event["target"] == actor:
            return {"action": "tsumo", "consumed": []}
        tile = state["lastAction"]["tile"]
        return {"action": "ron", "tile": tile, "calledTile": tile,
                "fromSeat": event["target"], "consumed": []}
    return None


def extract_game(events, game_id, *, match_metadata=None):
    """Return samples and exclusions; every emitted label matches a frozen mask."""
    if not events or events[0].get("type") != "start_game" or events[-1].get("type") != "end_game":
        raise ValueError("expected a complete MJAI game")
    players = len(events[0].get("names", []))
    if players not in (3, 4):
        raise ValueError("Expected a three- or four-player MJAI game")
    match_metadata = validate_match_metadata(match_metadata, game_id)
    source = (match_metadata or {}).get("sourcePlatform", "majsoul")
    if players == 3 and source != "tenhou":
        raise ValueError("Three-player conversion requires source-bound Tenhou metadata")
    if match_metadata and match_metadata["playerCount"] != players:
        raise ValueError("Match metadata player count differs")
    if source == "tenhou":
        header = events[0].get("_tenhou", {})
        if (header.get("game_id") != game_id or
                header.get("GO", {}).get("type") != str(match_metadata["goType"]) or
                header.get("xml_sha256") != match_metadata["provenance"]["xmlSha256"]):
            raise ValueError("MJAI Tenhou header differs from source metadata")
    length = "east" if match_metadata and match_metadata["roundCount"] == 1 else "half"
    engine_mode = f"{players}p-red-{length}"
    env = RiichiEnv(game_mode=engine_mode, rule=(GameRule.default_tenhou() if source == "tenhou"
                                              else GameRule.default_mjsoul()))
    public = MjaiVisibleState(match_metadata, players)
    temporary, permanent = [False] * players, [False] * players
    discard_furiten, response_waiting = [False] * players, set()
    pending, samples, excluded = {}, [], Counter()
    rounds, blocked, declared = -1, False, None
    kan_count, replacement_actor = 0, None
    audit = {"gameId": game_id, "sourceFormat": "mjai", "operationSource": "riichienv-reconstructed",
             "engineVersion": ENGINE_VERSION, "officialOperationLists": False,
             "sourcePlatform": source, "playerCount": players, "ruleEngineRules": source,
             "matchMetadata": match_metadata, "ruleEngineGameMode": engine_mode,
             "ruleEngineMatchLengthAssumed": match_metadata is None}

    def emit(window, action, label_source):
        if action is None:
            excluded["unresolved_action"] += 1
            return False
        key = action_key(action)
        if key not in window["keys"]:
            excluded["label_not_in_reconstructed_mask"] += 1
            return False
        samples.append({"schemaVersion": 1, "ruleset": RULESET, "gameId": game_id,
                        "roundId": str(rounds), "decisionId": window["id"],
                        "seat": window["state"]["selfSeat"], "state": window["state"],
                        "action": action, "labelSource": label_source,
                        "sourceFormat": "mjai", "operationSource": "riichienv-reconstructed",
                        "engineVersion": ENGINE_VERSION, "sourcePlatform": source,
                        "ruleEngineRules": source})
        return True

    for index, event in enumerate(events):
        kind = event["type"]
        verified_daiminkan = False
        replacement_draw = False
        if kind == "start_kyoku":
            if pending:
                excluded["unfinished_window"] += len(pending)
            pending.clear()
            rounds += 1
            blocked, declared = False, None
            kan_count, replacement_actor = 0, None
            temporary, permanent = [False] * players, [False] * players
            discard_furiten, response_waiting = [False] * players, set()
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
                    accepted = emit(window, actual, "inferred_pass" if actual and actual["action"] == "pass" else "accepted")
                    verified_daiminkan |= accepted and kind == "daiminkan"
                elif kind == "ryukyoku" and not response:
                    emit(window, actual, "accepted")
                elif response and kind == "tsumo" and event["actor"] == (last["seat"] + 1) % players:
                    emit(window, {"action": "pass", "consumed": []}, "inferred_pass")
                else:
                    excluded["censored_response" if response else "unresolved_self_action"] += 1
            pending.clear()
            if kind == "dahai":
                declared = None
        # Both sources mark a missed shape wait even without yaku / a ron
        # operation (Tenhou manual: 縛りをクリアしない待ち牌は同巡振聴).
        # Apply it only after the response closes.
        if kind in ("tsumo", "chi", "pon", "daiminkan"):
            for seat in response_waiting:
                temporary[seat] = True
                permanent[seat] |= bool(public.state["riichi"][seat] or public.state["riichiPending"][seat])
            response_waiting.clear()
        elif kind in ("hora", "ryukyoku", "end_kyoku", "end_game"):
            response_waiting.clear()
        if kind in ("tsumo", "dahai"):
            temporary[event["actor"]] = False
        if replacement_actor is not None and kind in RESOLVERS:
            replacement_draw = kind == "tsumo" and event["actor"] == replacement_actor
            if not replacement_draw and kind not in ("hora", "ryukyoku"):
                blocked = True
                excluded["hand_suffix_after_unverified_daiminkan_draw"] += 1
            replacement_actor = None
        if kind in KAN:
            kan_count += 1
            if kind != "daiminkan":
                blocked = True
                excluded["hand_suffix_after_kan"] += 1
            elif kan_count >= 4:
                # Four-kan abort timing differs from the ordinary call path.
                # Keep even a single player's legal fourth-kan suffix censored.
                blocked = True
                excluded["hand_suffix_after_four_kans"] += 1
            elif not blocked:
                if verified_daiminkan:
                    replacement_actor = event["actor"]
                else:
                    blocked = True
                    excluded["hand_suffix_after_unverified_daiminkan"] += 1
        if kind == "kita" and any(30 in env.get_observation(seat).waits
                                   for seat in range(players) if seat != event["actor"]):
            # Rob-North response masks are not yet audited by this extractor.
            # Hidden waits are used only to censor uncertain suffixes; they
            # never enter snapshots, features, or action candidates.
            blocked = True
            excluded["hand_suffix_after_rob_north_uncertainty"] += 1
        if kind in ("end_kyoku", "end_game"):
            excluded["unfinished_window"] += len(pending)
            pending.clear()
        if players == 3 or kan_count:
            # RiichiEnv 0.4.10's replay handler omits the replacement-draw
            # flag that its normal step() path sets. Without it an open
            # no-yaku hand can lose the legal rinshan tsumo candidate.
            if kind == "tsumo":
                last = public.state["lastAction"] or {}
                env.is_rinshan_flag = (replacement_draw or
                                      (players == 3 and last.get("name") == "ActionBaBei"
                                       and last.get("seat") == event["actor"]))
            elif kind in ("start_kyoku", "dahai"):
                env.is_rinshan_flag = False
        env.missed_agari_doujun = [a or b for a, b in zip(temporary, permanent)]
        env.apply_event(event)
        env.missed_agari_doujun = [a or b for a, b in zip(temporary, permanent)]
        public.apply(event, index)
        if players == 3 and not public.state["noCallsYet"]:
            env.is_first_turn = False
        if kind in ("dahai", "daiminkan") and not blocked:
            actor = event["actor"]
            discarded = {tile34(d["tile"]) for d in public.state["rivers"][actor]}
            discard_furiten[actor] = bool(discarded.intersection(env.get_observation(actor).waits))
        if kind == "dahai" and not blocked:
            response_waiting = {seat for seat in range(players) if seat != actor
                                and tile34(tile_name(event["pai"])) in env.get_observation(seat).waits}
        if blocked or kind not in ("tsumo", "dahai", "chi", "pon"):
            continue
        seats = [event["actor"]] if kind != "dahai" else [s for s in range(players) if s != event["actor"]]
        for seat in seats:
            observation = env.get_observation(seat)
            details = operation_details(env, seat, observation, public)
            if not details:
                continue
            hand = [_tile(t) for t in observation.hand]
            # A 14-tile draw has no shape waits. Preserve self-discard furiten
            # from the last completed discard until this player discards again.
            furiten = temporary[seat] or permanent[seat] or discard_furiten[seat]
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
