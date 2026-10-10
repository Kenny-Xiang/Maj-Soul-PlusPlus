"""Complete, unscored actions from one authoritative visible decision state."""
from collections import Counter
import json
import re


ACTION_SCHEMA_VERSION = 1
ACTION_TYPES = {"discard": 1, "chi": 2, "pon": 3, "ankan": 4, "daiminkan": 5,
                "shouminkan": 6, "riichi": 7, "tsumo": 8, "ron": 9, "abort": 10,
                "kita": 11, "pass": 0}
_NAMES = {value: key for key, value in ACTION_TYPES.items()}
_TILE = re.compile(r"(?:[0-9][mps]|[1-7]z)\Z")
_REACTIONS = {2, 3, 5, 9}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _family(tile):
    _require(isinstance(tile, str) and _TILE.fullmatch(tile), "Invalid tile")
    return "5" + tile[1] if tile[0] == "0" else tile


def action_key(action):
    """Stable semantic identity; exclude scores, server ordering and diagnostics."""
    _require(isinstance(action, dict), "Action must be an object")
    kind = action.get("action")
    _require(kind in ACTION_TYPES, "Unknown action")
    consumed = action.get("consumed", [])
    _require(isinstance(consumed, list), "Invalid consumed tiles")
    for tile in consumed:
        _family(tile)
    moqie = action.get("moqie")
    if kind in ("discard", "riichi", "kita"):
        _require(type(moqie) is bool, "Action requires explicit moqie")
    else:
        _require(moqie is None, "Action has no moqie parameter")
    return json.dumps([ACTION_SCHEMA_VERSION, kind, action.get("tile"), sorted(consumed),
                       action.get("calledTile"), action.get("fromSeat"),
                       action.get("meldIndex"), moqie], separators=(",", ":"))


def legal_actions(state):
    """Return every verified candidate, or reject the whole decision with ValueError.

    This is a server-operation adapter, not a rules engine for missing masks.
    A closed window has no candidates. An open but incomplete window is an error.
    No heuristic ranking, automatic win or speculative post-call discard is used.
    """
    try:
        return _legal_actions(state)
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError("Malformed decision state") from error


def _legal_actions(state):
    _require(isinstance(state, dict), "State must be an object")
    _require(state.get("phase") in ("playing", "waiting", "connected", "disconnected",
                                    "between_rounds", "ended", "stopped"), "Missing phase")
    if state.get("phase") != "playing":
        return []
    _require(type(state.get("canAct")) is bool, "Missing decision-window status")
    if not state["canAct"]:
        return []
    _require(state.get("handComplete") is True and state.get("historyComplete") is True
             and not state.get("recovery"), "Incomplete decision state")
    players, seat = state.get("playerCount"), state.get("selfSeat")
    _require(type(players) is int and players in (3, 4) and type(seat) is int
             and 0 <= seat < players, "Invalid player count or seat")
    hand = state.get("hand")
    _require(isinstance(hand, list) and hand, "Missing hand")

    def tiles(values):
        _require(isinstance(values, list), "Missing tiles")
        for tile in values:
            family = _family(tile)
            _require(players != 3 or family not in [f"{n}m" for n in range(2, 9)],
                     "Removed manzu tile in sanma")

    def physical(values):
        tiles(values)
        _require(all(count <= 4 for count in Counter(map(_family, values)).values()),
                 "More than four copies of a tile")
        _require(all(values.count(f"0{suit}") <= 1 for suit in "mps"),
                 "Multiple red fives in a normal ruleset")

    tiles(hand)
    melds, rivers = state.get("melds"), state.get("rivers")
    _require(all(isinstance(groups, list) and len(groups) >= players
                 and all(isinstance(group, list) for group in groups[:players])
                 for groups in (melds, rivers)), "Missing melds or rivers")
    own_melds = melds[seat]
    owned = list(hand)
    for meld in own_melds:
        _require(isinstance(meld, dict) and type(meld.get("type")) is int
                 and meld["type"] in (0, 1, 2, 3), "Invalid own meld")
        values = meld.get("tiles")
        tiles(values)
        _require(len(values) == (3 if meld["type"] < 2 else 4), "Invalid meld size")
        families = sorted(map(_family, values))
        if meld["type"] == 0:
            _require(players == 4 and families[0][1] != "z"
                     and len({tile[1] for tile in families}) == 1
                     and [int(tile[0]) for tile in families] == list(range(int(families[0][0]), int(families[0][0]) + 3)),
                     "Invalid chi meld")
        else:
            _require(len(set(families)) == 1, "Invalid pon or kan meld")
        owned.extend(values)
    physical(owned)
    flags = [state.get(key) for key in ("riichi", "riichiPending")]
    _require(all(isinstance(values, list) and len(values) >= players
                 and type(values[seat]) is bool for values in flags), "Unknown own riichi status")
    locked = any(values[seat] for values in flags)
    _require(type(state.get("lastStep")) is int and state["lastStep"] >= 0,
             "Missing action step")
    last = state.get("lastAction")
    _require(isinstance(last, dict) and last.get("step") == state["lastStep"],
             "Missing current action")
    _require(type(last.get("seat")) is int and 0 <= last["seat"] < players,
             "Invalid current actor")
    operations, details = state.get("operations"), state.get("operationDetails")
    _require(isinstance(operations, list) and operations
             and all(type(kind) is int and 1 <= kind <= 11 for kind in operations)
             and len(set(operations)) == len(operations), "Invalid server operations")
    _require(isinstance(details, list) and len(details) == len(operations),
             "Missing server operation details")
    offered = {}
    for detail in details:
        _require(isinstance(detail, dict) and type(detail.get("type")) is int
                 and detail["type"] in operations and detail["type"] not in offered,
                 "Inconsistent server operation details")
        combos = detail.get("combination")
        _require(isinstance(combos, list) and all(isinstance(value, str) for value in combos),
                 "Missing server combinations")
        offered[detail["type"]] = combos
    _require(type(state.get("canDiscard")) is bool and state["canDiscard"] == (1 in offered),
             "Inconsistent discard permission")
    reaction = bool(_REACTIONS.intersection(offered))
    _require(not reaction or set(offered) <= _REACTIONS, "Mixed own-turn and reaction operations")
    _require(len(hand) == (13 if reaction else 14) - 3 * len(own_melds),
             "Hand size does not match the decision phase")
    _require("lastDraw" in state, "Missing drawn-tile status")
    draw = state["lastDraw"]
    if reaction:
        _require(last.get("name") in ("ActionDiscardTile", "ActionAnGangAddGang", "ActionBaBei")
                 and last["seat"] != seat and draw is None, "Invalid reaction source")
        called = last.get("tile")
        tiles([called])
        if last["name"] == "ActionBaBei":
            _require(players == 3 and called == "4z", "Invalid robbed north")
        if last["name"] == "ActionDiscardTile":
            river = rivers[last["seat"]]
            _require(river and river[-1].get("tile") == called
                     and river[-1].get("step") == state["lastStep"]
                     and not river[-1].get("called"), "Stale called discard")
        physical(owned + [called])
    else:
        _require(last.get("name") in ("ActionNewRound", "ActionDealTile", "ActionChiPengGang")
                 and last["seat"] == seat, "Invalid own-turn source")
        if last["name"] == "ActionDealTile":
            _require(draw in hand and last.get("tile") == draw, "Unknown drawn tile")
        elif last["name"] == "ActionNewRound":
            _require(not own_melds and draw in hand, "Invalid opening hand")
        else:
            _require(draw is None and last.get("type") in (0, 1), "Invalid post-call window")
    # A dealer's last dealt tile is not a wire draw. The live core keeps it in
    # lastDraw for hand analysis, so the event origin must also be checked.
    drawn = draw if not reaction and last["name"] == "ActionDealTile" else None

    def sources(tile):
        result = []
        if hand.count(tile) > int(tile == drawn) and not locked:
            result.append(False)
        if tile == drawn:
            result.append(True)
        _require(result, "No legal physical source for the offered action")
        return result

    def owns(values):
        _require(not (Counter(values) - Counter(hand)), "Server combination consumes unavailable tiles")

    actions = []

    def add(kind, **values):
        choice = {"action": kind, "consumed": [], **values}
        choice["actionId"] = action_key(choice)
        actions.append(choice)

    prohibited = state.get("forbiddenDiscards")
    tiles(prohibited)
    _require(set(map(_family, prohibited)) == set(map(_family, offered.get(1, []))),
             "Inconsistent forbidden discards")
    discards = [tile for tile in sorted(set(hand)) if _family(tile) not in set(map(_family, prohibited))]
    if locked:
        discards = [tile for tile in discards if tile == drawn]
    for kind, combos in sorted(offered.items()):
        name = _NAMES[kind]
        if kind == 1:
            _require(discards, "No legal discard")
            for tile in discards:
                for moqie in sources(tile):
                    add(name, tile=tile, moqie=moqie)
        elif kind == 7:
            _require(1 in offered and not locked and all(m["type"] == 3 for m in own_melds)
                     and combos, "Invalid riichi offer")
            tiles(combos)
            for family in sorted(set(map(_family, combos))):
                allowed = [tile for tile in discards if _family(tile) == family]
                _require(allowed, "Riichi discard is not legal")
                for tile in allowed:
                    for moqie in sources(tile):
                        add(name, tile=tile, moqie=moqie)
        elif kind in (2, 3, 4, 5, 6):
            _require(combos, "Missing call or kan combinations")
            seen = set()
            for combination in combos:
                consumed = sorted(combination.split("|"))
                tiles(consumed)
                signature = tuple(consumed)
                _require(signature not in seen, "Ambiguous duplicate server combination")
                seen.add(signature)
                if kind in (2, 3, 5):
                    _require(not locked and last["name"] == "ActionDiscardTile"
                             and len(consumed) == (3 if kind == 5 else 2), "Invalid call offer")
                    families = sorted(map(_family, consumed + [called]))
                    if kind == 2:
                        _require(players == 4 and last["seat"] == (seat - 1) % players
                                 and families[0][1] != "z" and len({tile[1] for tile in families}) == 1
                                 and [int(tile[0]) for tile in families] == list(range(int(families[0][0]), int(families[0][0]) + 3)),
                                 "Invalid chi combination or source")
                    else:
                        _require(len(set(families)) == 1, "Invalid pon or daiminkan combination")
                    owns(consumed)
                    add(name, tile=called, consumed=consumed, calledTile=called, fromSeat=last["seat"])
                else:
                    _require(not reaction and len(consumed) == 4
                             and len(set(map(_family, consumed))) == 1, "Invalid kan combination")
                    if kind == 4:
                        owns(consumed)
                        add(name, tile=_family(consumed[0]), consumed=consumed)
                    else:
                        _require(not locked, "Added kan after riichi")
                        matching = [(index, meld) for index, meld in enumerate(own_melds)
                                    if meld["type"] == 1 and not (Counter(meld["tiles"]) - Counter(consumed))]
                        _require(len(matching) == 1, "Added kan has no unique matching pon")
                        index, meld = matching[0]
                        added = list((Counter(consumed) - Counter(meld["tiles"])).elements())
                        _require(len(added) == 1, "Invalid added tile")
                        owns(added)
                        add(name, tile=added[0], consumed=added, meldIndex=index)
        else:
            _require(combos in ([], [""]), "Unexpected parameterized operation")
            if kind == 8:
                _require(not reaction and last["name"] in ("ActionDealTile", "ActionNewRound"),
                         "Invalid tsumo window")
                add(name)
            elif kind == 9:
                add(name, tile=called, calledTile=called, fromSeat=last["seat"])
            elif kind == 10:
                terminals = {_family(tile) for tile in hand if tile[1] == "z" or _family(tile)[0] in "19"}
                _require(not locked and not own_melds and state.get("noCallsYet") is True
                         and not rivers[seat] and len(terminals) >= 9, "Invalid nine-terminals abort")
                add(name)
            elif kind == 11:
                _require(players == 3 and "4z" in hand, "Invalid north extraction")
                for moqie in sources("4z"):
                    add(name, tile="4z", consumed=["4z"], moqie=moqie)
    if 1 not in offered:
        add("pass")
    _require(actions, "Empty legal candidate set")
    return sorted(actions, key=lambda choice: choice["actionId"])
