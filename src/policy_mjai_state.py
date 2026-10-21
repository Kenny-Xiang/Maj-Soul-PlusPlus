"""Project MJAI events into the live policy's seat-visible state contract.

Legal operations are supplied by the replay rules engine, not inferred here.
Opponent starting hands, names, outcomes and future events are never retained.
"""
from copy import deepcopy
import re
from policy_metadata import validate_match_metadata


_TILE = re.compile(r"(?:[1-9][mps]|0[mps]|[1-7]z)\Z")
_HONORS = dict(zip("ESWNPFC", (f"{n}z" for n in range(1, 8))))
_PUBLIC_FIELDS = ("phase", "historyComplete", "baseline", "lastStep", "lastAction", "left",
                  "doras", "scores", "rivers", "melds", "north", "riichi", "riichiPending",
                  "doubleRiichi", "doubleRiichiPending", "riichiStep", "riichiSticks",
                  "noCallsYet", "playerCount", "round", "match", "recovery")


def tile_name(value):
    """Convert a visible MJAI tile to the application's red-preserving notation."""
    value = _HONORS.get(value, value)
    if isinstance(value, str) and value in ("5mr", "5pr", "5sr"):
        value = "0" + value[1]
    if not isinstance(value, str) or not _TILE.fullmatch(value):
        raise ValueError("Missing or invalid visible tile")
    return value


def _seat(value, players=4):
    if type(value) is not int or value not in range(players):
        raise ValueError("Expected an active player seat")
    return value


class MjaiVisibleState:
    def __init__(self, match_metadata=None, players=4):
        if type(players) is not int or players not in (3, 4):
            raise ValueError("Expected three or four players")
        self.players = players
        self.match_metadata = validate_match_metadata(match_metadata)
        if self.match_metadata and self.match_metadata["playerCount"] != players:
            raise ValueError("Match metadata player count differs")
        self.state = {"phase": "waiting", "historyComplete": False,
                      "baseline": None, "lastStep": None, "lastAction": None,
                      "left": None, "doras": [], "scores": [],
                      "rivers": [[] for _ in range(players)], "melds": [[] for _ in range(players)],
                      "north": [0] * players, "riichi": [False] * players,
                      "riichiPending": [False] * players, "doubleRiichi": [False] * players,
                      "doubleRiichiPending": [False] * players, "riichiStep": [None] * players,
                      "riichiSticks": 0, "noCallsYet": False, "playerCount": players,
                      "round": None, "match": {"playerCount": players, "roundCount": None},
                      "recovery": None}
        if self.match_metadata is not None:
            self.state["match"]["roundCount"] = self.match_metadata["roundCount"]
            if "modeId" in self.match_metadata:
                self.state["match"]["modeId"] = self.match_metadata["modeId"]
            if "sourcePlatform" in self.match_metadata:
                self.state["match"]["sourcePlatform"] = self.match_metadata["sourcePlatform"]
        self._draw_seat = self._draw_tile = None
        self._opening = False

    def _action(self, name, step, actor=None, tile=None, kind=None):
        self.state["lastStep"] = step
        self.state["lastAction"] = {"name": name, "seat": actor, "tile": tile,
                                    "type": kind, "step": step}

    def apply(self, event, step):
        """Apply one source event. Informational events preserve decision origin."""
        if type(step) is not int or step < 0:
            raise ValueError("Invalid event step")
        players = self.players
        kind = event["type"]
        if kind == "start_game":
            self.__init__(self.match_metadata, players)
            return
        if kind == "start_kyoku":
            scores = event["scores"]
            if not isinstance(scores, list) or len(scores) != players or any(type(score) is not int for score in scores):
                raise ValueError("Expected " + ("four" if players == 4 else "three") + " starting scores")
            dealer = _seat(event["oya"], players)
            wind = event["bakaze"]
            if wind not in ("E", "S", "W", "N"):
                raise ValueError("Invalid round wind")
            self.__init__(self.match_metadata, players)
            self.state.update(phase="playing", historyComplete=True, baseline="new_round",
                              scores=list(scores), left=70 if players == 4 else 55, doras=[tile_name(event["dora_marker"])],
                              riichiSticks=event.get("kyotaku", 0), noCallsYet=True,
                              round={"chang": "ESWN".index(wind), "ju": dealer,
                                     "ben": event.get("honba", 0)})
            self._opening = True
            return
        if not self.state["historyComplete"]:
            raise ValueError("Event before a complete round baseline")
        state = self.state
        if kind in ("hora", "ryukyoku", "end_kyoku", "end_game"):
            state["phase"] = "ended" if kind == "end_game" else "between_rounds"
            state["riichiPending"] = [False] * players
            state["doubleRiichiPending"] = [False] * players
            self._draw_seat = self._draw_tile = None
            return
        if state["phase"] != "playing":
            raise ValueError("Playing event outside an active round")
        if kind == "dora":
            state["doras"].append(tile_name(event["dora_marker"]))
            return
        if kind == "none":
            return
        actor = _seat(event["actor"], players)
        if kind == "reach":
            state["riichiPending"][actor] = True
            state["doubleRiichiPending"][actor] = state["noCallsYet"] and not state["rivers"][actor]
            return
        if kind == "reach_accepted":
            if state["riichi"][actor] or not state["riichiPending"][actor] or state["riichiStep"][actor] is None:
                raise ValueError("Missing or duplicate riichi declaration")
            state["scores"][actor] -= 1000
            state["riichiSticks"] += 1
            state["riichi"][actor] = True
            state["doubleRiichi"][actor] = state["doubleRiichiPending"][actor]
            state["riichiPending"][actor] = state["doubleRiichiPending"][actor] = False
            return
        if kind == "tsumo":
            tile = tile_name(event["pai"])
            if self._opening and actor != state["round"]["ju"]:
                raise ValueError("The opening draw must belong to the dealer")
            self._draw_seat, self._draw_tile = actor, tile
            state["left"] -= 1
            if state["left"] < 0:
                raise ValueError("More draws than the live wall permits")
            self._action("ActionNewRound" if self._opening else "ActionDealTile", step, actor)
            self._opening = False
            return
        if kind == "dahai":
            tile = tile_name(event["pai"])
            opening = (state["lastAction"] or {}).get("name") == "ActionNewRound"
            riichi = state["riichiPending"][actor]
            state["rivers"][actor].append({"tile": tile, "step": step,
                                            "moqie": False if opening else bool(event["tsumogiri"]),
                                            "riichi": riichi, "called": False})
            if riichi:
                state["riichiStep"][actor] = step
            self._action("ActionDiscardTile", step, actor, tile)
        elif kind in ("chi", "pon", "daiminkan"):
            if players == 3 and kind == "chi":
                raise ValueError("Chi is not supported in sanma")
            target, tile = _seat(event["target"], players), tile_name(event["pai"])
            river = state["rivers"][target]
            if target == actor or not river or river[-1]["tile"] != tile or river[-1]["called"]:
                raise ValueError("Call has no matching unclaimed discard")
            consumed = [tile_name(value) for value in event["consumed"]]
            meld_type = {"chi": 0, "pon": 1, "daiminkan": 2}[kind]
            if len(consumed) != (3 if meld_type == 2 else 2):
                raise ValueError("Invalid call size")
            river[-1]["called"] = True
            state["melds"][actor].append({"type": meld_type, "tiles": consumed + [tile],
                                           "froms": [actor] * len(consumed) + [target]})
            state["noCallsYet"] = False
            self._action("ActionChiPengGang", step, actor, kind=meld_type)
        elif kind == "ankan":
            consumed = [tile_name(value) for value in event["consumed"]]
            if len(consumed) != 4 or len({value.replace("0", "5") for value in consumed}) != 1:
                raise ValueError("Invalid concealed kan")
            tile = consumed[0].replace("0", "5")
            state["melds"][actor].append({"type": 3, "tiles": consumed, "froms": []})
            state["noCallsYet"] = False
            self._action("ActionAnGangAddGang", step, actor, tile, 3)
        elif kind == "kakan":
            tile = tile_name(event["pai"])
            matching = [meld for meld in state["melds"][actor]
                        if meld["type"] == 1 and meld["tiles"][0].replace("0", "5") == tile.replace("0", "5")]
            if len(matching) != 1:
                raise ValueError("Added kan requires one matching pon")
            matching[0]["type"] = 2
            matching[0]["tiles"].append(tile)
            matching[0]["froms"].append(actor)
            state["noCallsYet"] = False
            self._action("ActionAnGangAddGang", step, actor, tile, 2)
        elif kind == "kita":
            if players != 3 or tile_name(event["pai"]) != "4z":
                raise ValueError("Invalid north extraction")
            state["north"][actor] += 1
            state["noCallsYet"] = False
            self._action("ActionBaBei", step, actor, "4z")
        else:
            raise ValueError(f"Unsupported MJAI event: {kind}")
        self._draw_seat = self._draw_tile = None

    def snapshot(self, seat, hand, operation_details, furiten):
        """Return an isolated visible snapshot with external rules-engine actions."""
        seat = _seat(seat, self.players)
        if type(furiten) is not bool:
            raise ValueError("Expected known own furiten status")
        hand = [tile_name(value) for value in hand]
        details = [{"type": value["type"], "combination": list(value["combination"])}
                   for value in operation_details]
        state = deepcopy({key: self.state[key] for key in _PUBLIC_FIELDS})
        draw = self._draw_tile if seat == self._draw_seat else None
        if state["lastAction"] and state["lastAction"]["name"] in ("ActionNewRound", "ActionDealTile"):
            state["lastAction"]["tile"] = draw
        can_act = (state["phase"] == "playing" and state["historyComplete"]
                   and state["lastAction"] is not None and bool(hand) and bool(details))
        operations = [value["type"] for value in details]
        state.update(selfSeat=seat, hand=hand, handComplete=bool(hand), lastDraw=draw,
                     furiten=furiten, canAct=can_act, canDiscard=can_act and 1 in operations,
                     operations=operations, operationDetails=details,
                     operationSource="riichienv-reconstructed",
                     forbiddenDiscards=[tile for detail in details if detail["type"] == 1
                                        for tile in detail["combination"]],
                     canDoubleRiichi=can_act and state["noCallsYet"] and not state["rivers"][seat])
        return state
