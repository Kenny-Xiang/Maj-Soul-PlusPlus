"""Bounded, public-information riichi action advice.

Shanten, visible-tile counts and complete-hand scoring are rule calculations.
Win/deal-in probabilities and future values are deliberately *uncalibrated*
estimates, not a solved game or a claim about opponents' hidden tiles. Unseen
tiles include opponents' hands and the dead wall; they are never called live
wall tiles. The engine never sends game actions; riichi is considered only when offered.
"""
from collections import Counter
from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache
from math import fsum
import time

from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.hand_calculating.scores import ScoresCalculator
from mahjong.meld import Meld
from mahjong.shanten import Shanten
from advisor_policy import Outcome, TABLES, discard as _policy_discard, residual as _policy_residual, fold_table, ready_table
from advisor_settlement import opponent_payments


MODEL = "public-information-actions-ev-v7-policy-terminals (未校准启发式)"
SEARCH_SECONDS = 2.
# Public-evidence priors, not frequencies fitted to game records.
OPEN_YAKU_CONFIDENCE = .6
FLUSH_ROUTE_WEIGHT = .25
_SEARCH = ContextVar("advisor_search", default=None)
_HAND_VALUES = ContextVar("advisor_hand_values", default=None)
_POLICY_RISKS = ContextVar("advisor_policy_risks", default=None)
TILES = tuple(f"{n}{s}" for s in "mps" for n in range(1, 10)) + tuple(f"{n}z" for n in range(1, 8))
ORPHANS = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)
OPTIONS = OptionalRules(has_open_tanyao=True, has_aka_dora=True,
                        has_double_yakuman=True, kiriage=False)


def tile_index(tile):
    if not isinstance(tile, str) or len(tile) != 2 or tile[1] not in "mpsz":
        raise ValueError("牌编码无效")
    n = 5 if tile[0] == "0" and tile[1] != "z" else int(tile[0])
    if n < 1 or n > (7 if tile[1] == "z" else 9):
        raise ValueError("牌编码无效")
    return "mpsz".index(tile[1]) * 9 + n - 1


def counts34(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile_index(tile)] += 1
    return tuple(counts)


@lru_cache(maxsize=65536)
def shanten(counts, special=True):
    return Shanten.calculate_shanten(counts, use_chiitoitsu=special, use_kokushi=special)


def _dora_index(tile, players):
    index = tile_index(tile)
    if index < 27:
        return 8 if players == 3 and index == 0 else index // 9 * 9 + (index + 1) % 9
    if index < 31:
        return 27 + (index - 26) % 4
    return 31 + (index - 30) % 3


def unseen_counts(state):
    """Count physical tiles once, even when a river tile has been called."""
    physical = [4] * 34
    if state.get("playerCount") == 3:
        physical[1:8] = [0] * 7
    known = list(state["hand"])
    for river in state.get("rivers", []):
        known.extend(d["tile"] for d in river if not d.get("called"))
    for melds in state.get("melds", []):
        for meld in melds:
            known.extend(meld["tiles"])
    known.extend(state.get("doras", []))
    known.extend(["4z"] * sum(state.get("north", [])))
    for tile in known:
        physical[tile_index(tile)] -= 1
    if min(physical) < 0:
        raise ValueError("已知牌超过实体张数，等待可信牌局状态")
    return tuple(physical)


def _improvements(counts, remaining, special):
    current = shanten(counts, special)
    result = []
    for index, count in enumerate(remaining):
        if not count or counts[index] == 4:
            continue
        trial = list(counts)
        trial[index] += 1
        if shanten(tuple(trial), special) < current:
            result.append({"tile": TILES[index], "count": count})
    return result


def _structural_waits(counts, special, players, meld_counts=None):
    # Include exhausted waits: an exhausted tile in one's river still makes the
    # entire hand furiten. Ukeire alone is not sufficient for this check.
    waits = []
    for index in range(34):
        if counts[index] + (meld_counts[index] if meld_counts else 0) >= 4 or (players == 3 and 1 <= index <= 7):
            continue
        trial = list(counts)
        trial[index] += 1
        if shanten(tuple(trial), special) == -1:
            waits.append(index)
    return waits


def _config(state, tsumo=False, seat=None):
    seat = state["selfSeat"] if seat is None else seat
    players = state["playerCount"]
    round_ = state.get("round") or {}
    return HandConfig(is_tsumo=tsumo,
                      is_rinshan=bool(state.get("replacementWin", False)),
                      is_riichi=bool(state.get("riichi", [False] * 4)[seat]),
                      is_daburu_riichi=bool(state.get("doubleRiichi", [False] * 4)[seat]),
                      player_wind=27 + (seat - round_.get("ju", 0)) % players,
                      round_wind=27 + round_.get("chang", 0) % 4,
                      kyoutaku_number=state.get("riichiSticks", 0),
                      tsumi_number=round_.get("ben", 0), options=OPTIONS)


def _points(han, fu, config, players, yakuman=False):
    cost = ScoresCalculator.calculate_scores(han, fu, config, yakuman)
    # Standard sanma tsumo-loss: remove the missing player's payment. Honba
    # is 200 on ron and 100 from each of two opponents on tsumo.
    total = cost["total"]
    if players == 3:
        total -= (cost["additional"] + cost["additional_bonus"] if config.is_tsumo
                  else 100 * config.tsumi_number)
    return total


def _scoring_tiles(concealed, meld_data):
    used = set()

    def allocate(tile):
        base = tile_index(tile) * 4
        if tile[0] == "0":
            choices = [base]
        elif base in (16, 52, 88):
            choices = [base + 1, base + 2, base + 3, base]
        else:
            choices = range(base, base + 4)
        result = next((i for i in choices if i not in used), None)
        if result is None:
            raise ValueError("手牌与副露重复使用同一实体牌")
        used.add(result)
        return result

    # Allocate explicit red fives first so normal fives cannot occupy them.
    all_groups = [concealed] + [m["tiles"] for m in meld_data]
    ids = [[None] * len(group) for group in all_groups]
    for red in (True, False):
        for group, values in zip(all_groups, ids):
            for n, tile in enumerate(group):
                if (tile[0] == "0") == red:
                    values[n] = allocate(tile)
    # The scorer expects the lowest chi tile first. Sort a copy: the allocation
    # order below must still match the original tile strings for implicit reds.
    melds = [Meld(Meld.CHI if m["type"] == 0 else Meld.PON if m["type"] == 1 else Meld.KAN,
                  sorted(ids[n + 1]), opened=m["type"] != 3)
             for n, m in enumerate(meld_data)]
    # A kan encoded as four ordinary fives carries no known aka information.
    # Avoid assigning an invented red bonus merely because IDs require slot 0.
    implicit_red = sum(i in (16, 52, 88) and t[0] != "0"
                       for group, values in zip(all_groups, ids) for t, i in zip(group, values))
    return [i for group in ids for i in group], ids[0][-1], melds, implicit_red


def _hand_value(concealed, winning_tile, state, tsumo):
    _check_search()
    cache = _HAND_VALUES.get()
    if cache is None:
        return _score_hand(concealed, winning_tile, state, tsumo)
    seat = state["selfSeat"]
    round_ = state.get("round") or {}
    # Preserve physical red identity and every input read by the scorer/config.
    # These values change along riichi, call and replacement continuations.
    key = (tuple(concealed), winning_tile, tsumo, seat, state["playerCount"],
           tuple((m["type"], tuple(m["tiles"])) for m in state["melds"][seat]),
           bool(state.get("replacementWin", False)),
           bool(state.get("riichi", [False] * 4)[seat]),
           bool(state.get("doubleRiichi", [False] * 4)[seat]),
           round_.get("ju", 0), round_.get("chang", 0), round_.get("ben", 0),
           state.get("riichiSticks", 0), state.get("north", [0] * 4)[seat],
           tuple(state.get("doras", [])), tuple(vars(OPTIONS).items()))
    if key not in cache:
        cache[key] = _score_hand(concealed, winning_tile, state, tsumo)
    value = cache[key]
    # Keep each caller's result independent, including the only nested field.
    return {**value, "yaku": value["yaku"].copy()} if "yaku" in value else value.copy()


def _score_hand(concealed, winning_tile, state, tsumo):
    seat, players = state["selfSeat"], state["playerCount"]
    tiles, win, melds, implicit_red = _scoring_tiles(concealed + [winning_tile], state["melds"][seat])
    config = _config(state, tsumo)
    nuki = state.get("north", [0] * 4)[seat]
    dora = [_dora_index(t, players) for t in state.get("doras", [])]
    extra = nuki * (1 + dora.count(30)) - implicit_red

    class GameScores(ScoresCalculator):
        @staticmethod
        def calculate_scores(han, fu, config, is_yakuman=False):
            result = ScoresCalculator.calculate_scores(han if is_yakuman else han + extra,
                                                        fu, config, is_yakuman)
            if players == 3:
                result["total"] -= (result["additional"] + result["additional_bonus"]
                                    if config.is_tsumo else 100 * config.tsumi_number)
            return result

    indicators = [(7 if players == 3 and tile_index(t) == 0 else tile_index(t)) * 4
                  for t in state.get("doras", [])]
    value = HandCalculator.estimate_hand_value(tiles, win, melds=melds,
                                               dora_indicators=indicators, config=config,
                                               scores_calculator_factory=GameScores)
    if value.error:
        return {"points": 0, "error": value.error}
    yakuman = any(y.is_yakuman for y in value.yaku)
    return {"points": value.cost["total"], "han": value.han + (0 if yakuman else extra),
            "fu": value.fu, "yaku": [y.name for y in value.yaku]}


def _wait_values(hand, counts, remaining, state, discard, special):
    meld_counts = counts34(t for m in state["melds"][state["selfSeat"]] for t in m["tiles"])
    waits = _structural_waits(counts, special, state["playerCount"], meld_counts)
    own_river = {tile_index(d["tile"]) for d in state["rivers"][state["selfSeat"]]}
    if discard is not None:
        own_river.add(tile_index(discard))
    # A normal own draw clears temporary furiten. Its server flag can still
    # reflect old discard-based waits, which must be recomputed after each
    # hypothetical discard. A call or confirmed riichi cannot clear that flag.
    retain_server_furiten = state.get("lastDraw") is None or state.get("riichi", [False] * 4)[state["selfSeat"]]
    furiten = bool(own_river.intersection(waits)) or bool(state.get("furiten", False) and retain_server_furiten)
    known_red = {t for t in state["hand"] if t.startswith("0")}
    known_red.update(d["tile"] for river in state["rivers"] for d in river if d["tile"].startswith("0"))
    known_red.update(t for melds in state["melds"] for meld in melds for t in meld["tiles"] if t.startswith("0"))
    known_red.update(t for t in state.get("doras", []) if t.startswith("0"))
    values = []
    for index in waits:
        tile = TILES[index]
        ron = _hand_value(hand, tile, state, False)
        tsumo = _hand_value(hand, tile, state, True)
        red_count = int(index in (4, 13, 22) and (state["playerCount"] == 4 or index != 4)
                        and f"0{tile[1]}" not in known_red and remaining[index] > 0)
        red_ron = _hand_value(hand, f"0{tile[1]}", state, False) if red_count else ron
        red_tsumo = _hand_value(hand, f"0{tile[1]}", state, True) if red_count else tsumo
        divisor = max(1, remaining[index])
        normal_weight = divisor - red_count
        values.append({"tile": tile, "count": remaining[index], "redCount": red_count,
                       "ronPoints": 0 if furiten else (ron["points"] * normal_weight + red_ron["points"] * red_count) / divisor,
                       "tsumoPoints": (tsumo["points"] * normal_weight + red_tsumo["points"] * red_count) / divisor,
                       "normalRonPoints": 0 if furiten else ron["points"],
                       "normalTsumoPoints": tsumo["points"],
                       "redRonPoints": 0 if furiten else red_ron["points"],
                       "redTsumoPoints": red_tsumo["points"],
                       "han": tsumo.get("han", ron.get("han", 0)),
                       "fu": tsumo.get("fu", ron.get("fu", 0)),
                       "yaku": tsumo.get("yaku", ron.get("yaku", []))})
    return values, furiten


def _future_value(hand, state, counts, special):
    """Conservative hand-shape projection, not a completed-hand score."""
    seat, players = state["selfSeat"], state["playerCount"]
    melds = state["melds"][seat]
    closed = all(m["type"] == 3 for m in melds)
    all_tiles = hand + [t for m in melds for t in m["tiles"]]
    full = counts34(all_tiles)
    cfg = _config(state)
    if special and Shanten.calculate_shanten_for_kokushi_hand(counts) == shanten(counts, special) <= 2:
        return _points(13, 0, cfg, players, yakuman=True), 1.
    value_han = sum(full[i] >= 3 for i in (31, 32, 33, cfg.player_wind, cfg.round_wind))
    simple = all(i < 27 and i % 9 not in (0, 8) for i, n in enumerate(full) if n)
    value_han += int(simple)
    if special and Shanten.calculate_shanten_for_chiitoitsu_hand(counts) <= 1:
        value_han = max(value_han, 2)
    suits = {i // 9 for i, n in enumerate(full[:27]) if n}
    if len(suits) == 1:
        value_han += (3 if closed else 2) if sum(full[27:]) else (6 if closed else 5)
    known_yaku = value_han > 0 or closed
    # Closed hands have a plausible menzen-tsumo route; no unrequested riichi
    # bonus, ippatsu, ura dora, or speculative rare yaku are inserted.
    value_han = max(value_han, 1 if closed else 0)
    doras = [_dora_index(t, players) for t in state.get("doras", [])]
    bonus = sum(full[i] for i in doras) + sum(t[0] == "0" for t in all_tiles)
    bonus += state.get("north", [0] * 4)[seat] * (1 + doras.count(30))
    estimated = _points(max(1, value_han) + bonus, 30, cfg, players)
    return estimated, (1.0 if known_yaku else .3)


def _visible_yakuman_payment(state, enemy):
    """Single-ron payment floor from public melds, never the winner's pot.

    Meld order records when sets became public, including a pon later extended
    to a kan. Missing source metadata leaves a half/full pao interval. Shared
    liability's honba allocation is not specified by the snapshot, so retain
    zero/all honba bounds rather than inventing a settlement.
    """
    melds = state["melds"][enemy]
    if len(melds) < 3:
        return None
    groups = [(tile_index(m["tiles"][0]), m) for m in melds
              if m["type"] in (1, 2, 3)]
    cfg = _config(state, seat=enemy)
    cfg.kyoutaku_number = cfg.tsumi_number = 0
    lower, upper, shared, names = 0, 0, False, []
    for name, indices, multiple in (("Daisangen", {31, 32, 33}, 1),
                                     ("Daisuushii", {27, 28, 29, 30}, 2)):
        relevant = [m for index, m in groups if index in indices]
        if {index for index, _ in groups} >= indices:
            names.append(name)
            last = relevant[-1]
            sources = {s for s in last.get("froms", [])
                       if s in range(state["playerCount"]) and s != enemy}
            payer = enemy if last["type"] == 3 else next(iter(sources)) if len(sources) == 1 else None
            full = _points(13 * multiple, 0, cfg, state["playerCount"], yakuman=True)
            split = payer not in (enemy, state["selfSeat"])
            lower += full // 2 if split else full
            upper += full // 2 if split and payer is not None else full
            shared |= split
    if len(melds) == 4 and all(m["type"] in (2, 3) for m in melds):
        names.append("Suukantsu")  # No pao for four kans in the supported rules.
        full = _points(13, 0, cfg, state["playerCount"], yakuman=True)
        lower += full
        upper += full
    if not names:
        return None
    honba = (state["playerCount"] - 1) * 100 * (state.get("round") or {}).get("ben", 0)
    return {"yaku": names, "lower": lower + (0 if shared else honba), "upper": upper + honba}


def _opponents(state, remaining, *, after_current=False, passed_discard=None):
    """Public risk features, optionally after known discards have survived.

    Continuations may include the current river event and an explicit root
    discard as locked-hand safety evidence without advancing the event clock.
    """
    opponents = []
    cache = _POLICY_RISKS.get()
    players, seat = state["playerCount"], state["selfSeat"]
    dora = [_dora_index(t, players) for t in state.get("doras", [])]
    for enemy in range(players):
        if enemy == seat:
            continue
        river, melds = state["rivers"][enemy], state["melds"][enemy]
        riichi = bool(state.get("riichi", [False] * 4)[enemy] or
                      state.get("riichiPending", [False] * 4)[enemy])
        safe = {tile_index(d["tile"]) for d in river}
        step = state.get("riichiStep", [None] * 4)[enemy]
        if riichi and step is not None:
            safe.update(tile_index(d["tile"]) for r in state["rivers"] for d in r
                        if step < d.get("step", -1) and
                        (d.get("step", -1) < state.get("lastStep", -1) or
                         after_current and d.get("step", -1) == state.get("lastStep", -1)))
        if riichi and passed_discard is not None:
            safe.add(tile_index(passed_discard))
        # Our hypothetical actions do not alter another player's public
        # groups, bonus tiles or river length within this one decision.
        # Rebuild safety for every continuation; never share that mutable set.
        key = ("opponent-public", enemy)
        if cache is not None and key in cache:
            opponents.append({**cache[key], "safe": safe})
            continue
        open_melds = [m for m in melds if m["type"] != 3]
        turn = len(river)
        # Four completed groups leave a singleton, not necessarily a legal ron
        # wait. A concealed kan advances structure without opening the hand.
        tenpai = 1.0 if riichi or len(melds) == 4 else min(.65, .04 + turn * .018 + len(melds) * .14)
        cfg = _config(state, seat=enemy)
        cfg.kyoutaku_number = 0  # Existing deposits are not paid by the discarder.
        visible = [t for m in melds for t in m["tiles"]]
        visible_counts = counts34(visible)
        yakuhai = sum(visible_counts[i] >= 3 for i in (31, 32, 33, cfg.player_wind, cfg.round_wind))
        han = (3 if riichi else max(1, yakuhai)) + sum(visible_counts[i] for i in dora)
        han += sum(t[0] == "0" for t in visible)
        han += state.get("north", [0] * 4)[enemy] * (1 + dora.count(30))
        fu = 40 if riichi or not open_melds else 30
        public_fu = 20 + (10 if not open_melds else 0) + (2 if len(melds) == 4 else 0)
        for meld in melds:
            index = tile_index(meld["tiles"][0])
            if meld["type"] != 0:
                public_fu += (16 if meld["type"] == 3 else 8 if meld["type"] == 2 else 2) * (
                    2 if index in ORPHANS else 1)
        fu = max(fu, (public_fu + 9) // 10 * 10)
        suits = {tile_index(t) // 9 for t in visible if tile_index(t) < 27}
        suited_melds = sum(any(tile_index(t) < 27 for t in m["tiles"]) for m in melds)
        flush_suit = next(iter(suits)) if len(suits) == 1 and (suited_melds >= 2 or len(melds) == 4) else None
        yakuman = _visible_yakuman_payment(state, enemy)
        loss = yakuman["lower"] if yakuman else _points(han, fu, cfg, players)
        red_loss = loss if yakuman else _points(han + 1, fu, cfg, players)
        opponents.append({"seat": enemy, "safe": safe, "tenpai": tenpai,
                          "loss": loss, "riichi": riichi, "dora": dora,
                          "redLoss": red_loss, "yakumanPayment": yakuman,
                          "openMeldCount": len(open_melds), "meldCount": len(melds),
                          "visibleCounts": visible_counts, "yakuhai": yakuhai,
                          "allTriplets": len(melds) == 4 and all(m["type"] != 0 for m in melds),
                          "flushSuit": flush_suit,
                          "flushWeight": min(.5, FLUSH_ROUTE_WEIGHT * (suited_melds - 1))
                          if flush_suit is not None else 0.,
                          "han": han, "fu": fu, "publicFu": public_fu, "config": cfg,
                          "playerCount": players, "canKokushi": not melds})
        if cache is not None:
            cache[key] = {k: v for k, v in opponents[-1].items() if k != "safe"}
    return opponents


def _ron_evidence(tile, enemy, *, chankan=False):
    cache = _POLICY_RISKS.get()
    key = ("ron-price", enemy["seat"], tile, chankan)
    if cache is not None and key in cache:
        return cache[key]
    result = _uncached_ron_evidence(tile, enemy, chankan=chankan)
    if cache is not None:
        cache[key] = result
    return result


def _uncached_ron_evidence(tile, enemy, *, chankan=False):
    """Conditional yaku/route weight and payment, separate from readiness.

    Unknown yaku keeps nonzero mass: hidden and event yaku are not enumerated.
    Mix point-weighted hits, never han before the nonlinear score table.
    """
    index = tile_index(tile)
    four = enemy["meldCount"] == 4
    counts = enemy["visibleCounts"]
    simple = four and index not in ORPHANS and all(i not in ORPHANS for i, n in enumerate(counts) if n)
    known_han = enemy["yakuhai"] + 2 * enemy["allTriplets"] + int(simple)
    # Added-kan robbery supplies eligibility; North extraction does not.
    confidence = 1. if chankan or enemy["riichi"] or not enemy["openMeldCount"] or known_han else OPEN_YAKU_CONFIDENCE
    compatible = enemy["flushSuit"] is not None and (index >= 27 or index // 9 == enemy["flushSuit"])
    # With four honor groups, a suited tanki pair establishes honitsu's suit.
    compatible |= four and index < 27 and not any(counts[:27])
    weight = float(compatible) if four else enemy["flushWeight"]
    ordinary = (1 - weight) * confidence
    flush = weight * compatible
    factor = ordinary + flush
    if enemy["yakumanPayment"]:
        return factor, enemy["loss"]
    bonus = enemy["han"] - (3 if enemy["riichi"] else max(1, enemy["yakuhai"]))
    # On a four-group tanki hit the concealed singleton is the same dora too;
    # its red identity is still unknown and must not be invented.
    bonus += enemy["dora"].count(index) * (2 if four else 1) + int(tile[0] == "0")
    han = max(3 if enemy["riichi"] else 1, known_han) + bonus
    cfg = enemy["config"]
    pair_fu = 2 * (int(index >= 31) + int(index == cfg.player_wind) + int(index == cfg.round_wind))
    fu = max(enemy["fu"], (enemy["publicFu"] + pair_fu + 9) // 10 * 10) if four else enemy["fu"]
    payment = _points(han, fu, cfg, enemy["playerCount"])
    if not flush:
        return factor, payment
    flush_han = (5 if four and index < 27 and not any(counts[27:]) else 2)
    flush_han += int(not enemy["openMeldCount"])
    flush_payment = _points(known_han + int(enemy["riichi"]) + flush_han + bonus, fu, cfg, enemy["playerCount"])
    return factor, (ordinary * payment + flush * flush_payment) / factor


def _physical_ron_shape(index, remaining, enemy):
    """Necessary tile availability, not a claim about an opponent's hand.

    A pair needs one hidden copy (also covering chiitoitsu); a triplet needs
    two, so cannot survive when the pair is excluded. Each sequence needs
    both companions. Four completed groups can only wait for a pair.
    """
    if remaining[index] > 0:
        return "pair"
    if enemy["meldCount"] == 4:
        return None
    if index < 27:
        suit, number = index // 9 * 9, index % 9
        for start in range(max(0, number - 2), min(number, 6) + 1):
            if all(remaining[j] > 0 for j in range(suit + start, suit + start + 3) if j != index):
                return "sequence"
    # A missing singleton can complete kokushi without another copy of itself.
    # The other twelve types and their pair must still have physical copies.
    if enemy["canKokushi"] and index in ORPHANS:
        others = [remaining[j] for j in ORPHANS if j != index]
        if all(others) and max(others) >= 2:
            return "kokushi"
    return None


def _danger(tile, remaining, opponents, *, chankan=False):
    cache = _POLICY_RISKS.get()
    if cache is None:
        return _uncached_danger(tile, remaining, opponents, chankan=chankan)
    # Within one advise call our hypothetical actions cannot change opponents'
    # public melds/prices. Passed-tile safety and physical counts can change.
    index = tile_index(tile)
    relevant = {index}
    if index < 27:
        relevant.update(j for j in range(max(0, index - 2), min(27, index + 3)) if j // 9 == index // 9)
    if index in ORPHANS:
        relevant.update(ORPHANS)  # A missing kokushi tile depends on every orphan.
    # Ordinary shapes inspect at most two neighbours; four-group tanki also
    # uses total unknown mass. Far-away non-orphans cannot change this risk.
    key = ("danger", tile, tuple(remaining[j] for j in sorted(relevant)), sum(remaining), chankan,
           tuple((o["seat"], tuple(sorted(o["safe"])), o["tenpai"]) for o in opponents))
    if key not in cache:
        cache[key] = _uncached_danger(tile, remaining, opponents, chankan=chankan)
    return cache[key]


def _uncached_danger(tile, remaining, opponents, *, chankan=False):
    index = tile_index(tile)
    survival, expected_loss, details = 1., 0., []
    for enemy in opponents:
        factor, loss = _ron_evidence(tile, enemy, chankan=chankan)
        physical_shape = _physical_ron_shape(index, remaining, enemy)
        if index in enemy["safe"]:
            shape = 0.
            reason = "现物"
        elif physical_shape is None:
            shape = 0.
            reason = "实体枚数排除全部荣和形状"
        elif enemy["meldCount"] == 4:
            # The sole concealed tile has an explicitly uniform unknown-tile
            # prior. Tanki types are mutually exclusive; suji/walls do not apply.
            shape = remaining[index] / max(1, sum(remaining)) if enemy["visibleCounts"][index] < 3 else 0.
            reason = "四组面子单骑（仍需实体等待及役）"
        elif physical_shape == "kokushi":
            shape = .001
            reason = "仅国士仍有实体等待"
        elif index >= 27:
            shape = (0., .025, .065, .10, .12)[remaining[index]]
            reason = "字牌剩余枚数"
        else:
            n = index % 9
            shape = .065 if n in (0, 8) else .10
            # Suji only discounts two-sided waits, never makes a tile safe.
            suji = ((n < 3 and index + 3 in enemy["safe"]) or
                    (n > 5 and index - 3 in enemy["safe"]) or
                    (3 <= n <= 5 and index - 3 in enemy["safe"] and index + 3 in enemy["safe"]))
            if suji:
                shape *= .5
            # A visible wall blocks some sequence waits; pair waits remain.
            if any(remaining[j] == 0 for j in (index - 1, index + 1)
                   if 0 <= j < 27 and j // 9 == index // 9):
                shape *= .75
            reason = "筋（仍可能放铳）" if suji else "无安全依据"
        if index in enemy["dora"] and enemy["meldCount"] != 4:
            shape *= 1.2
        conditional = shape * factor
        chance = conditional * enemy["tenpai"]
        survival *= 1 - chance
        expected_loss += chance * loss
        details.append({"seat": enemy["seat"], "probability": round(chance, 4),
                        "tenpaiProbability": round(enemy["tenpai"], 4),
                        "conditionalRonProbability": round(conditional, 4),
                        "yakuConfidence": factor, "lossPoints": round(loss, 1), "reason": reason})
        if enemy["yakumanPayment"]:
            details[-1]["yakumanPayment"] = enemy["yakumanPayment"]
    return 1 - survival, expected_loss, details


def _opportunities(state, after_discard=False):
    """Ordered own draws and enemy discards, excluding the current action.

    A draw already reflected in ``left`` still has a pending enemy discard.
    Legacy snapshots without action metadata assume the position after our
    discard; a hypothetical discard always establishes that order explicitly.
    """
    players, seat = state["playerCount"], state["selfSeat"]
    start, prefix = (seat + 1) % players, ()
    action = state.get("lastAction") or {}
    actor, name = action.get("seat"), action.get("name")
    if (not after_discard and isinstance(actor, int) and actor in range(players) and
            action.get("step") == state.get("lastStep")):
        if name == "ActionDiscardTile":
            start = (actor + 1) % players
        elif name in ("ActionDealTile", "ActionNewRound") or (name == "ActionChiPengGang" and action.get("type") in (0, 1)):
            prefix = (actor,) if actor != seat else ()
            start = (actor + 1) % players
        elif name in ("ActionAnGangAddGang", "ActionBaBei") or (name == "ActionChiPengGang" and action.get("type") == 2):
            start = actor
    return prefix + tuple((start + i) % players for i in range(min(state["left"], 24 * players)))


def _event_survival(opponents):
    # Preserve the existing full-cycle competition factor at finer granularity.
    competition = min(.22, .025 + sum(o["tenpai"] for o in opponents) * .04)
    return (1 - competition) ** (1 / (len(opponents) + 1))


def _win_model(sh, ukeire, unseen, draws, opponents, waits, projected=None, yaku_factor=1., tail=0,
               opportunities=None, own_seat=0):
    if not unseen or not ukeire:
        return 0., 0.
    if opportunities is None:
        opportunities = ((own_seat,) + (None,) * len(opponents)) * draws + (None,) * tail
    survival = _event_survival(opponents)
    if waits is not None:
        outcomes = {}
        for key, rate, cap in (("tsumoPoints", 1., 1.), ("ronPoints", .45, .65)):
            mass = sum(w["count"] for w in waits if w[key])
            points = sum(w["count"] * w[key] for w in waits) / mass if mass else 0.
            outcomes[key] = (min(cap, mass / unseen * rate), points)
        live, win, ev = 1., 0., 0.
        for actor in opportunities:
            hit, points = outcomes["tsumoPoints" if actor == own_seat else "ronPoints"]
            win += live * hit
            ev += live * hit * points
            live *= (1 - hit) * survival
        return min(1., win), ev / win if win else 0.
    # A small absorbing Markov chain needs sh+1 effective draws. Later-stage
    # ukeire is projected; it is not held equal to the current wide ukeire.
    final_waits = projected if projected is not None else 6.
    rates = [min(.9, (min(32, ukeire) if k == 0 else
                     max(final_waits, min(16 * .60 ** (k - 1), ukeire * .60 ** k))) / unseen)
             for k in range(sh)] + [min(.8, final_waits / unseen)]
    ron_rate = min(.8, final_waits / unseen * .45)
    active = [1.] + [0.] * sh
    win = 0.
    for actor in opportunities:
        if actor != own_seat:
            win += active[-1] * ron_rate * yaku_factor
            active[-1] *= 1 - ron_rate
            active = [mass * survival for mass in active]
            continue
        next_ = [0.] * len(active)
        for stage, mass in enumerate(active):
            hit = mass * rates[stage]
            if stage == sh:
                win += hit * yaku_factor
            else:
                next_[stage + 1] += hit * survival
            next_[stage] += mass * (1 - rates[stage]) * survival
        active = next_
    return min(1., win), 0.


def _one_shanten_branches(hand, counts, improvements, remaining, state, discard, special):
    """Every effective physical draw and legal discard into a scored wait."""
    after = deepcopy(state)
    after["hand"] = hand.copy()
    if discard is not None:
        after["rivers"][state["selfSeat"]].append({"tile": discard})
    effective = {tile_index(t["tile"]) for t in improvements}
    branches = []
    for draw, weight in sorted(_draw_pool(after, remaining)):
        _check_search()
        index = tile_index(draw)
        if index not in effective:
            continue
        drawn = deepcopy(after)
        drawn["hand"].append(draw)
        drawn["lastDraw"] = draw
        drawn["forbiddenDiscards"] = []  # The preceding call's kuikae window ended.
        unseen = list(remaining)
        unseen[index] -= 1
        # Reaching this draw proves the known current and root discards passed.
        opponents = _opponents(drawn, unseen, after_current=True, passed_discard=discard)
        options = []
        for tile in sorted(_legal_discards(drawn)):
            _check_search()
            next_hand = _remove_exact(drawn["hand"], [tile])
            trial = list(counts)
            trial[index] += 1
            trial[tile_index(tile)] -= 1
            trial = tuple(trial)
            if shanten(trial, special) == 0:
                waits, furiten = _wait_values(next_hand, trial, unseen, drawn, tile, special)
                danger, loss, _ = _danger(tile, unseen, opponents)
                options.append({"discard": tile, "hand": tuple(next_hand), "waits": waits, "furiten": furiten,
                                "dealInProbability": danger, "expectedDealInLoss": loss})
        branches.append({"draw": draw, "count": weight, "remaining": tuple(unseen), "options": options,
                         "state": drawn, "rootHand": tuple(hand), "rootDiscard": discard})
    return branches


def _ready_choices(branch, opponents, opportunities, state):
    choices = []
    drawn = branch.get("state", state)
    for option in branch["options"]:
        _check_search()
        hand = option.get("hand", tuple(t for t in drawn["hand"] if t != option["discard"]))
        # Reaching this branch proves earlier discards passed. The option's
        # own discard is also safe only on its surviving future continuation.
        future = _opponents(drawn, branch["remaining"], after_current=True,
                            passed_discard=option["discard"])
        if branch.get("rootDiscard") is not None:
            for enemy in future:
                if enemy["riichi"]:
                    enemy["safe"].add(tile_index(branch["rootDiscard"]))
        table = _ready_policy(hand, drawn, branch["remaining"], future,
                              opportunities, option["waits"])
        choices.append((option, table))
    return choices


def _ready_result(option, continuation, state):
    outcome = _policy_discard(continuation, option["dealInProbability"], option["expectedDealInLoss"])
    ukeire = sum(w["count"] for w in option["waits"])
    efficiency = (420 + 2 * ukeire) * (1 - outcome.fold)
    probability, value, _, _ = outcome.metrics()
    return {**option, "winProbability": probability, "expectedWinPoints": value,
            "score": round(outcome.utility(_risk_weight(state)) + efficiency, 1),
            "ukeire": ukeire, "outcome": outcome}


def _ready_discard(branch, unseen, opponents, opportunities, state):
    """The same ready policy, root risk and score used by an expanded window."""
    outcomes = [_ready_result(option, table[0], state)
                for option, table in _ready_choices(branch, opponents, opportunities, state)]
    return min(outcomes, key=lambda c: (-c["score"], -c["ukeire"],
                                        c["discard"].startswith("0"), c["discard"])) if outcomes else None


def _one_shanten_outcome(branches, unseen, opponents, opportunities, state, *, hand=None, remaining=None, discard=None):
    """First effective arrival without replacement, then a frozen ready policy.

    Exact effective draws and ready discards are retained. Ineffective draws
    pay for either a tsumogiri or an irreversible fold; no free retreat keeps
    the old win probability. Later hidden changes and miss identities are not
    expanded. Every ready suffix is computed once, with the same horizon.
    """
    if not branches:
        remaining = unseen_counts(state) if remaining is None else remaining
        future = _opponents(state, remaining, after_current=True, passed_discard=discard)
        return _ready_policy(hand if hand is not None else state["hand"], state,
                             remaining, future, opportunities, [])[0]
    first = branches[0]
    hand = first.get("rootHand", state["hand"])
    remaining = list(first["remaining"])
    remaining[tile_index(first["draw"])] += 1
    future = _opponents(state, remaining, after_current=True, passed_discard=first.get("rootDiscard"))
    rows, stock, average = _policy_risks(hand, state, remaining, future)
    survival, payments, fees = _policy_environment(state, future)
    folded = fold_table(opportunities, state["selfSeat"], stock, average,
                        survival, payments, fees[0], _check_search)
    effective = sum(b["count"] for b in branches)
    families = {tile_index(b["draw"]) for b in branches}
    misses = [(n, r, l) for t, n, r, l in rows if tile_index(t) not in families]
    miss_total = sum(n for n, _, _ in misses)
    miss_risk = (sum(n * r for n, r, _ in misses) / miss_total if miss_total else 0.,
                 sum(n * l for n, _, l in misses) / miss_total if miss_total else 0.)
    choices = [(b, _ready_choices(b, future, opportunities, state))
               for b in sorted(branches, key=lambda b: b["draw"])]
    own_before, count = [], 0
    for actor in opportunities:
        own_before.append(count)
        count += actor == state["selfSeat"]
    result = Outcome(draw=1., draw_income=fees[0])
    weight = _risk_weight(state)
    for i in range(len(opportunities) - 1, -1, -1):
        _check_search()
        nxt = _policy_residual(result, survival, *payments)
        if opportunities[i] != state["selfSeat"]:
            result = nxt
            continue
        pool = max(effective, unseen - own_before[i], 1)
        fold = folded[i][0]._replace(fold=1.)
        attack = _policy_discard(nxt, *miss_risk)
        miss = fold if fold.utility(weight) > attack.utility(weight) else attack
        result = miss.scale(max(0., 1 - effective / pool))
        for branch, options in choices:
            outcomes = [_ready_result(o, _policy_residual(t[i + 1], survival, *payments), state)
                        for o, t in options]
            if outcomes:
                selected = min(outcomes, key=lambda c: (-c["score"], -c["ukeire"],
                                                        c["discard"].startswith("0"), c["discard"]))
                best = selected["outcome"]
                if fold.utility(weight) > selected["score"]:
                    best = fold
            else:
                best = fold
            result += best.scale(branch["count"] / pool)
    return result


def _one_shanten_model(branches, unseen, opponents, opportunities, state):
    return _one_shanten_outcome(branches, unseen, opponents, opportunities, state).metrics()


def _kokushi_probability(counts, remaining, draws, opponents, state, discard, tail, opportunities=None):
    """Small shape-state model for missing orphans and whether a pair exists.

    Using generic wide ukeire here can incorrectly prefer breaking an existing
    pair. Tracking these actual prerequisites preserves that basic dominance.
    Draw chances still use unknown-pool estimates, not knowledge of the wall.
    """
    missing = tuple(i for i in ORPHANS if counts[i] == 0)
    initial_mask = (1 << len(missing)) - 1
    paired = any(counts[i] >= 2 for i in ORPHANS)
    unseen = sum(remaining)
    if not unseen:
        return 0.
    active = {(initial_mask, paired): 1.}
    own_river = {tile_index(d["tile"]) for d in state["rivers"][state["selfSeat"]]}
    if discard is not None:
        own_river.add(tile_index(discard))
    if opportunities is None:
        opportunities = ((state["selfSeat"],) + (None,) * len(opponents)) * draws + (None,) * tail
    survival = _event_survival(opponents)
    win = 0.

    def ron_probability(mask, pair):
        if pair and mask.bit_count() == 1:
            waits = [missing[k] for k in range(len(missing)) if mask & (1 << k)]
        elif not pair and mask == 0:
            waits = list(ORPHANS)
        else:
            return 0.
        if own_river.intersection(waits):
            return 0.
        mass = sum(remaining[i] - int(i in missing and not mask & (1 << missing.index(i))) for i in waits)
        return min(.65, max(0, mass) / unseen * .45)

    for actor in opportunities:
        if actor != state["selfSeat"]:
            for (mask, pair), mass in active.copy().items():
                ron = ron_probability(mask, pair)
                win += mass * ron
                active[(mask, pair)] = mass * (1 - ron) * survival
            continue
        next_ = {}
        for (mask, pair), mass in active.items():
            transitions = []
            for k, index in enumerate(missing):
                if mask & (1 << k):
                    transitions.append(((mask & ~(1 << k), pair), remaining[index] / unseen))
            if not pair:
                pair_mass = sum(remaining[i] for i in ORPHANS if counts[i] > 0)
                pair_mass += sum(remaining[i] - 1 for k, i in enumerate(missing) if not mask & (1 << k))
                transitions.append(((mask, True), max(0, pair_mass) / unseen))
            transitions.append(((mask, pair), max(0., 1 - sum(p for _, p in transitions))))
            for target, probability in transitions:
                if target == (0, True):
                    win += mass * probability
                else:
                    next_[target] = next_.get(target, 0.) + mass * probability
        active = {target: mass * survival for target, mass in next_.items()}
    return min(1., win)


def _kokushi_outcome(counts, remaining, opponents, state, discard, opportunities, value):
    """Keep actual missing-orphan/pair prerequisites in the terminal ledger.

    This coarse push route uses the frozen average future-discard risk on
    every non-winning draw, including progress draws. It does not claim a
    cost-free fold or exact future surplus-tile choices. Root discard risk
    is applied by the caller, as for other continuation policies.
    """
    missing = tuple(i for i in ORPHANS if counts[i] == 0)
    paired = any(counts[i] >= 2 for i in ORPHANS)
    active = {((1 << len(missing)) - 1, paired): 1.}
    unseen = max(1, sum(remaining))
    own_river = {tile_index(d["tile"]) for d in state["rivers"][state["selfSeat"]]}
    if discard is not None:
        own_river.add(tile_index(discard))
    hand = [TILES[i] for i, count in enumerate(counts) for _ in range(count)]
    _, _, average = _policy_risks(hand, state, remaining, opponents)
    survival, payments, fees = _policy_environment(state, opponents)
    ending = _policy_residual(Outcome(), survival, *payments)
    result = Outcome()

    def waits(mask, pair):
        if pair and mask.bit_count() == 1:
            return [missing[k] for k in range(len(missing)) if mask & (1 << k)]
        return list(ORPHANS) if not pair and mask == 0 else []

    for actor in opportunities:
        _check_search()
        next_ = {}
        for (mask, pair), mass in active.items():
            if actor != state["selfSeat"]:
                winning = waits(mask, pair)
                ron_mass = sum(remaining[i] - int(i in missing and not mask & (1 << missing.index(i)))
                               for i in winning)
                hit = 0. if own_river.intersection(winning) else min(.65, max(0, ron_mass) / unseen * .45)
                result += Outcome(win=mass * hit, income=mass * hit * value)
                live = mass * (1 - hit)
                result += ending.scale(live)
                next_[(mask, pair)] = next_.get((mask, pair), 0.) + live * survival
                continue
            transitions = [((mask & ~(1 << k), pair), remaining[index] / unseen)
                           for k, index in enumerate(missing) if mask & (1 << k)]
            if not pair:
                pair_mass = sum(remaining[i] for i in ORPHANS if counts[i] > 0)
                pair_mass += sum(remaining[i] - 1 for k, i in enumerate(missing) if not mask & (1 << k))
                transitions.append(((mask, True), max(0, pair_mass) / unseen))
            transitions.append(((mask, pair), max(0., 1 - sum(p for _, p in transitions))))
            for target, probability in transitions:
                branch = mass * probability
                if target == (0, True):
                    result += Outcome(win=branch, income=branch * value)
                    continue
                result += Outcome(deal=branch * average[0], loss=branch * average[1])
                live = branch * (1 - average[0])
                result += ending.scale(live)
                next_[target] = next_.get(target, 0.) + live * survival
        active = next_
    for (mask, pair), mass in active.items():
        result += Outcome(draw=mass, draw_income=mass * fees[bool(waits(mask, pair))])
    return result


def _rank_context(state):
    """Small, uncalibrated preferences gated by a caller-confirmed final round.

    The capture layer does not yet know match length. In particular, south 4
    alone is not evidence that a custom match is ending. Ties stay intervals;
    initial seating and settlement rules are not inferred from current seats.
    """
    players, seat = state["playerCount"], state["selfSeat"]
    scores = state.get("scores", [])[:players]
    round_ = state.get("round") or {}
    active = round_.get("isFinal") is True
    result = {"active": active, "source": "explicit-round-marker" if active else "unknown-match-length",
              "objective": "points", "riskWeightAdjustment": 0.,
              "dealer": round_.get("ju") == seat}
    if len(scores) != players:
        result.update(active=False, source="incomplete-scores")
        return result
    own = scores[seat]
    above = sum(score > own for score in scores)
    tied = sum(score == own for score in scores)
    result["rankRange"] = [above + 1, above + tied]
    result["gapToFirst"] = max(scores) - own
    result["gapAboveLast"] = own - min(scores)
    if not active or tied > 1:
        return result
    if above == 0:
        result.update(objective="protect-first", riskWeightAdjustment=.25)
    elif above == players - 1:
        # A dealer can retain another hand; accept less extra risk than a
        # non-dealer chasing from last. This is a preference, not continuation EV.
        result.update(objective="escape-last",
                      riskWeightAdjustment=-.075 if result["dealer"] else -.15)
    elif above == players - 2 and result["gapAboveLast"] <= 8000:
        result.update(objective="avoid-last", riskWeightAdjustment=.20)
    return result


def _risk_weight(state):
    players, seat = state["playerCount"], state["selfSeat"]
    scores = state.get("scores", [])
    weight = 1.15
    if len(scores) >= players:
        rivals = [scores[i] for i in range(players) if i != seat]
        weight += .3 if scores[seat] - max(rivals) >= 8000 else 0
        weight -= .15 if scores[seat] < min(rivals) else 0
        weight += .2 if scores[seat] < 8000 else 0
    if (state.get("round") or {}).get("isFinal") is True:
        weight += _rank_context(state)["riskWeightAdjustment"]
    return weight


def _draw_payments(opponents, players):
    """Expected noten/tenpai transfer at an ordinary exhaustive draw.

    Enumerate independent opponent readiness, rather than awarding a fixed
    late bonus. Structural tenpai (including furiten/no yaku) earns the fee.
    Frozen readiness and independence remain uncalibrated approximations.
    """
    distribution = [1.]
    for enemy in opponents:
        p = enemy["tenpai"]
        nxt = [0.] * (len(distribution) + 1)
        for count, mass in enumerate(distribution):
            nxt[count] += mass * (1 - p)
            nxt[count + 1] += mass * p
        distribution = nxt
    pool = 3000 if players == 4 else 2000
    noten = -fsum(mass * pool / (players - n) for n, mass in enumerate(distribution) if n)
    tenpai = fsum(mass * pool / (n + 1) for n, mass in enumerate(distribution) if n < players - 1)
    return noten, tenpai


def _policy_environment(state, opponents):
    cache = _POLICY_RISKS.get()
    key = ("environment", tuple((o["seat"], o["tenpai"]) for o in opponents))
    if cache is not None and key in cache:
        return cache[key]
    total = sum(o["tenpai"] for o in opponents)
    payments = [opponent_payments(state, o) for o in opponents]
    # The old residual event rate is preserved, partitioned into tsumo (40%)
    # and other-player ron (60%). Neither this split nor readiness is fitted.
    mean = tuple(sum(p[k] * o["tenpai"] for p, o in zip(payments, opponents)) / total
                 if total else 0. for k in range(2))
    result = _event_survival(opponents), mean, _draw_payments(opponents, state["playerCount"])
    if cache is not None:
        cache[key] = result
    return result


def _policy_risks(hand, state, remaining, opponents):
    """One physical draw at a time; freeze only subsequent unknown changes."""
    pool = tuple(_draw_pool(state, remaining))
    cache = _POLICY_RISKS.get()
    # Opponent pricing is invariant inside one decision; only passed-tile
    # safety and the unseen pool change along our hypothetical continuations.
    key = (tuple(remaining), pool, tuple((o["seat"], tuple(sorted(o["safe"])), o["tenpai"])
                                       for o in opponents))
    rows = cache.get(key) if cache is not None else None
    if rows is None:
        rows = []
        for tile, count in pool:
            _check_search()
            after = list(remaining)
            after[tile_index(tile)] -= 1
            risk, loss, _ = _danger(tile, after, opponents)
            rows.append((tile, count, risk, loss))
        if cache is not None:
            cache[key] = rows
    unseen = max(1, sum(remaining))
    average = (sum(n * r for _, n, r, _ in rows) / unseen,
               sum(n * l for _, n, _, l in rows) / unseen)
    stock = []
    for tile, count in sorted(Counter(hand).items()):
        risk, loss, _ = _danger(tile, remaining, opponents)
        stock.extend([(risk, loss)] * count)
    stock.sort(key=lambda r: (r[1], r[0]))
    return rows, stock, average


def _ready_policy(hand, state, remaining, opponents, events, waits, locked=False):
    _check_search()
    cache = TABLES.get()
    key = ("ready-input", tuple(sorted(hand)), tuple(remaining), tuple(_draw_pool(state, remaining)),
           tuple((o["seat"], tuple(sorted(o["safe"])), o["tenpai"]) for o in opponents),
           tuple(events), tuple(sorted((w["tile"], w["count"], w["ronPoints"], w["tsumoPoints"]) for w in waits)),
           locked, _risk_weight(state))
    if cache is not None and key in cache:
        return cache[key]
    rows, stock, average = _policy_risks(hand, state, remaining, opponents)
    unseen = max(1, sum(remaining))
    # Use the existing per-family red-weighted winning values; keep physical
    # red identity for dangerous non-winning draws.
    points = {tile_index(w["tile"]): w["tsumoPoints"] for w in waits}
    draws = [(count / unseen, points.get(tile_index(tile), 0), risk, loss)
             for tile, count, risk, loss in rows]
    if not draws:
        draws = [(1., 0., 0., 0.)]
    mass = sum(w["count"] for w in waits if w["ronPoints"])
    hit = min(.65, mass / unseen * .45)
    income = hit * sum(w["count"] * w["ronPoints"] for w in waits) / mass if mass else 0.
    survival, payments, fees = _policy_environment(state, opponents)
    if not waits:
        fees = (fees[0], fees[0])
    result = ready_table(events, state["selfSeat"], (hit, income), draws, stock, average,
                         survival, payments, fees, _risk_weight(state), locked, _check_search)
    if cache is not None:
        cache[key] = result
    return result


def _coarse_policy(hand, state, remaining, opponents, events, sh, ukeire, value, yaku_factor):
    """Projected progress beyond one shanten, with paid future discards.

    This coarse push policy does not invent safe retreat or precise future
    hands. Its projected ready state and payment remain heuristic.
    """
    _, _, average = _policy_risks(hand, state, remaining, opponents)
    unseen = max(1, sum(remaining))
    survival, payments, fees = _policy_environment(state, opponents)
    rates = [min(.9, (min(32, ukeire) if k == 0 else
                     max(6., min(16 * .60 ** (k - 1), ukeire * .60 ** k))) / unseen)
             for k in range(sh)] + [min(.8, 6. / unseen)]
    stages = [Outcome(draw=1., draw_income=fees[int(k == sh)]) for k in range(sh + 1)]
    for actor in reversed(events):
        _check_search()
        suffix = [_policy_residual(o, survival, *payments) for o in stages]
        nxt = []
        for k in range(sh + 1):
            if actor != state["selfSeat"]:
                hit = min(.8, 6. / unseen * .45) * yaku_factor if k == sh else 0.
                nxt.append(suffix[k].scale(1 - hit) + Outcome(win=hit, income=hit * value))
            elif k == sh:
                hit = rates[k] * yaku_factor
                nxt.append(_policy_discard(suffix[k], *average).scale(1 - hit) +
                           Outcome(win=hit, income=hit * value))
            else:
                continuation = suffix[k + 1].scale(rates[k]) + suffix[k].scale(1 - rates[k])
                nxt.append(_policy_discard(continuation, *average))
        stages = nxt
    return stages[0]


def _position_score(probability, value, loss, sh, ukeire, waits, state, own_draws):
    """Shared score for a present discard and a future ready-hand decision."""
    efficiency = 70 * (6 - sh) + 2 * ukeire
    # Share the pre-discard progress requirement across candidates: otherwise
    # scaling their common score offset differently can itself encourage risk.
    # Unknown future calls are not part of this necessary-draw estimate.
    if sh > 0:
        required = max(1, shanten(counts34(state["hand"]), not state["melds"][state["selfSeat"]]))
        efficiency *= min(1., max(0, own_draws - required + 1) / required)
    return probability * value - _risk_weight(state) * loss + efficiency, efficiency, 0.


def _record_score(candidate, **terms):
    """Diagnose the existing score; never use this ledger to rank candidates.

    The adjustment includes earlier rounding when scores are extended or
    averaged, as well as the final rounding of this candidate.
    """
    terms = {key: value for key, value in terms.items() if key != "roundingAdjustment" and value}
    terms["roundingAdjustment"] = candidate["score"] - fsum(terms.values())
    candidate["scoreBreakdown"] = terms


def _position(hand, state, remaining, discard=None):
    """Evaluate a 13-tile-equivalent position with a common score scale."""
    special = not state["melds"][state["selfSeat"]]
    counts = counts34(hand)
    sh = shanten(counts, special)
    improvements = _improvements(counts, remaining, special)
    ukeire, unseen = sum(t["count"] for t in improvements), sum(remaining)
    opponents = _opponents(state, remaining)
    opportunities = _opportunities(state, after_discard=discard is not None)
    draws = opportunities.count(state["selfSeat"])
    danger, loss, detail = _danger(discard, remaining, opponents) if discard is not None else (0., 0., [])
    waits, furiten = _wait_values(hand, counts, remaining, state, discard, special) if sh == 0 else (None, False)
    value, yaku_factor = _future_value(hand, state, counts, special)
    kokushi_route = special and sh == 2 and Shanten.calculate_shanten_for_kokushi_hand(counts) == sh
    branches = None
    locked = bool(state.get("riichi", [False] * 4)[state["selfSeat"]])
    future_opponents = _opponents(state, remaining, after_current=True, passed_discard=discard)
    if locked or sh == 0:
        continuation = _ready_policy(hand, state, remaining, future_opponents,
                                     opportunities, waits or [], locked)[0]
    elif sh == 1:
        branches = _one_shanten_branches(hand, counts, improvements, remaining, state, discard, special)
        continuation = _one_shanten_outcome(branches, unseen, opponents, opportunities, state,
                                           hand=hand, remaining=remaining, discard=discard)
        yaku_factor = float(any(w["ronPoints"] or w["tsumoPoints"]
                               for b in branches for o in b["options"] for w in o["waits"]))
    elif kokushi_route:
        continuation = _kokushi_outcome(counts, remaining, future_opponents, state,
                                        discard, opportunities, value)
    else:
        continuation = _coarse_policy(hand, state, remaining, future_opponents,
                                      opportunities, sh, ukeire, value, yaku_factor)
    future_danger = continuation.deal * (1 - danger)
    future_loss = continuation.loss * (1 - danger)
    outcome = _policy_discard(continuation, danger, loss)
    probability, value, _, _ = outcome.metrics()
    reasons = [f"{'听牌' if sh == 0 else str(sh) + ' 向听'}；有效未见牌 {ukeire} 张"]
    if sh == 0 and not waits:
        reasons[0] = "形式 0 向听，但没有实体上合法的听口"
    if furiten:
        reasons.append("整副牌振听，所有等待均只估自摸")
    if sh == 0 and not any(w["ronPoints"] or w["tsumoPoints"] for w in waits):
        reasons.append("当前等待无役，不能仅凭宝牌和牌")
    if detail and all(d["probability"] == 0 for d in detail):
        reasons.append("对各家均有现物或实体枚数安全依据")
    elif any(o["riichi"] for o in opponents):
        reasons.append("有对手立直，已计入较高放铳风险")
    if discard and discard[0] == "0":
        reasons.append("打出赤宝牌，打点下降")
    if yaku_factor != 1 and sh:
        reasons.append("一向听前瞻未找到有役等待" if sh == 1 else "副露后役尚未确定，和牌前景已折减")
    if kokushi_route:
        reasons.append("国士路线按缺少幺九及雀头估计推进")
    _, efficiency, _ = _position_score(
        probability, value, loss + future_loss, sh, ukeire, waits, state, draws)
    efficiency *= 1 - outcome.fold
    score = outcome.utility(_risk_weight(state)) + efficiency
    if sh >= 2 and not locked and (discard is None or loss <= min(
            _danger(t, remaining, opponents)[1] for t in _legal_discards(state))):
        # A remote hand need not commit to the coarse perpetual-push path.
        # The alternative is a complete greedy fold starting NOW with a
        # minimum-loss legal discard, not a dangerous probe justified by
        # hypothetical new safety. Ties receive the same continuation model.
        # Its win and efficiency income are both zero.
        _, stock, average = _policy_risks(hand, state, remaining, future_opponents)
        survival, payments, fees = _policy_environment(state, future_opponents)
        folded = fold_table(opportunities, state["selfSeat"], stock, average,
                            survival, payments, fees[0], _check_search)[0][0]._replace(fold=1.)
        folded_root = _policy_discard(folded, danger, loss)
        if folded_root.utility(_risk_weight(state)) > score:
            outcome = folded_root
            future_danger, future_loss = folded.deal * (1 - danger), folded.loss * (1 - danger)
            probability, value, _, _ = outcome.metrics()
            efficiency = 0.
            score = outcome.utility(_risk_weight(state))
            reasons.append("高向听持续进攻不及按现有手牌转守；不再保留进攻收益或效率奖励")
    result = {"tile": discard, "action": "discard" if discard is not None else "pass",
              "actionId": f"discard:{discard}" if discard is not None else "pass", "consumed": [],
              "shanten": sh, "ukeire": ukeire, "improvingTiles": improvements,
              "winningTiles": waits or [], "hasValidWait": bool(waits) if sh == 0 else None,
              "furiten": furiten, "winProbability": round(probability, 4),
              "expectedWinPoints": round(value), "dealInProbability": round(danger, 4),
              "expectedDealInLoss": round(loss), "dealInPoints": round(loss / danger) if danger else 0,
              "dealInLossIfHit": round(loss / danger) if danger else 0,
              "score": round(score, 1), "reasons": reasons, "opponentRisks": detail,
              "valueMethod": "听牌逐张计分" if sh == 0 else "一向听逐分支计分" if sh == 1 else "未来牌型估值",
              "yakuConfidence": yaku_factor}
    _record_score(result, winIncome=probability * value, currentDealInLoss=-loss,
                  futureDiscardDealInLoss=-future_loss if not locked else 0,
                  futureForcedDealInLoss=-future_loss if locked else 0,
                  riskPreferenceAdjustment=-(_risk_weight(state) - 1) * (loss + future_loss),
                  efficiencyReward=efficiency, opponentTsumoLoss=-outcome.tsumo_loss,
                  otherRonLiabilityLoss=-outcome.other_loss, exhaustiveDrawPayment=outcome.draw_income)
    result.update(terminalProbabilities={"selfWin": outcome.win, "dealIn": outcome.deal,
                                        "opponentTsumo": outcome.tsumo, "otherRon": outcome.other,
                                        "exhaustiveDraw": outcome.draw},
                  expectedOpponentTsumoLoss=round(outcome.tsumo_loss, 3),
                  expectedOtherRonLiabilityLoss=round(outcome.other_loss, 3),
                  expectedDrawPayment=round(outcome.draw_income, 3),
                  futureFoldProbability=round(outcome.fold, 4))
    if locked:
        result.update(futureForcedDealInProbability=round(future_danger, 4),
                      futureForcedDealInLoss=round(future_loss))
        reasons.append("立直后不能自由弃和，和牌与强制摸切放铳共用存活概率")
    else:
        result.update(futureDiscardDealInProbability=round(future_danger, 4),
                      futureDiscardDealInLoss=round(future_loss))
    if branches is not None:
        result["lookahead"] = {"drawVariants": len(branches),
                               "readyDiscards": sum(len(b["options"]) for b in branches)}
        reasons.append("枚举有效进张及听牌弃牌；无效摸牌与维持听牌均计风险，转守同时放弃后续和牌收益")
    elif sh >= 2:
        reasons.append("二向听以上按近似进攻路线计未来弃牌损失，进张、等待与打点仍为估计")
    if sh == 0 and not locked:
        reasons.append("逐次比较继续保听与用手中牌转守；转守放弃和牌及听牌料，不保留免费收益")
    reasons.append("终局互斥核算他家自摸及流局收支；终局概率和他家听牌仍未校准")
    return result


def _legal_discards(state):
    prohibited = {tile_index(t) for t in state.get("forbiddenDiscards", [])}
    legal = [t for t in dict.fromkeys(state["hand"]) if tile_index(t) not in prohibited]
    if state.get("riichi", [False] * 4)[state["selfSeat"]]:
        draw = state.get("lastDraw")
        if draw not in legal:
            raise ValueError("立直后摸切牌不明确，暂停推荐")
        return [draw]
    return legal


def _discards(state, remaining):
    candidates = []
    for tile in _legal_discards(state):
        _check_search()
        hand = state["hand"].copy()
        hand.remove(tile)
        candidates.append(_position(hand, state, remaining, tile))
    return candidates


def _remove_exact(hand, consumed):
    result = hand.copy()
    for tile in consumed:
        result.remove(tile)
    return result


def _action_choices(state):
    """Decode only server-offered combinations; never invent an operation."""
    choices, warnings = [], []
    mapping = {2: "chi", 3: "pon", 4: "ankan", 5: "daiminkan", 6: "shouminkan", 7: "riichi", 10: "abort", 11: "kita"}
    hand, seat = state["hand"], state["selfSeat"]
    for kind in state.get("operations", []):
        if kind not in mapping:
            if kind not in (1, 8, 9):
                warnings.append(f"未支持操作 {kind}，已略过")
            continue
        details = [op for op in state.get("operationDetails", []) if isinstance(op, dict) and op.get("type") == kind]
        if not details:
            warnings.append(f"{mapping[kind]} 缺少服务端组合，已略过")
            continue
        for detail in details:
            combos = detail.get("combination")
            if not isinstance(combos, list) or not all(isinstance(c, str) for c in combos):
                warnings.append(f"{mapping[kind]} 组合格式不完整，已略过")
                continue
            if kind in (10, 11):
                combos = [""] if combos == [] else combos
            for combination in combos:
                try:
                    consumed = combination.split("|") if combination else []
                    for tile in consumed:
                        tile_index(tile)
                    choice = {"action": mapping[kind], "consumed": consumed}
                    if kind == 7:
                        if len(consumed) != 1:
                            raise ValueError("立直弃牌不完整")
                        allowed = consumed + (["5" + consumed[0][1]] if consumed[0][0] == "0" else [])
                        legal = _legal_discards(state)
                        for tile in dict.fromkeys(allowed):
                            if tile in legal:
                                choices.append({"action": "riichi", "tile": tile, "consumed": [], "actionId": f"riichi:{tile}"})
                        if not any(t in legal for t in allowed):
                            raise ValueError("立直弃牌不在手中")
                        continue
                    if kind in (2, 3, 5):
                        if state.get("riichi", [False] * 4)[seat]:
                            raise ValueError("立直后不能鸣牌")
                        offered = state.get("lastAction") or {}
                        source = offered.get("seat")
                        if (offered.get("name") != "ActionDiscardTile" or source == seat or
                                not isinstance(source, int) or source not in range(state["playerCount"]) or
                                offered.get("step") != state.get("lastStep")):
                            raise ValueError("缺少当前可鸣牌的弃牌")
                        called = offered.get("tile")
                        family = tile_index(called)
                        river = state["rivers"][source]
                        if not river or river[-1].get("called") or river[-1]["tile"] != called or river[-1].get("step") != offered["step"]:
                            raise ValueError("弃牌历史与鸣牌目标不一致")
                        expected = 3 if kind == 5 else 2
                        if len(consumed) != expected:
                            raise ValueError("鸣牌消耗张数不完整")
                        indices = sorted(tile_index(t) for t in consumed + [called])
                        if kind == 2:
                            if (state["playerCount"] != 4 or source != (seat - 1) % 4 or indices[0] >= 27 or
                                    indices != list(range(indices[0], indices[0] + 3)) or indices[0] // 9 != indices[-1] // 9):
                                raise ValueError("吃牌组合不合法")
                        elif any(i != family for i in indices):
                            raise ValueError("碰杠牌种不一致")
                        choice.update(calledTile=called, fromSeat=source, tile=called)
                    elif kind == 4:
                        if len(consumed) != 4 or len({tile_index(t) for t in consumed}) != 1:
                            raise ValueError("暗杠组合不完整")
                        choice["tile"] = consumed[0]
                    elif kind == 6:
                        if len(consumed) != 4 or len({tile_index(t) for t in consumed}) != 1:
                            raise ValueError("加杠组合不完整")
                        matches = [(i, m) for i, m in enumerate(state["melds"][seat])
                                   if m["type"] == 1 and Counter(m["tiles"]) <= Counter(consumed)]
                        if len(matches) != 1:
                            raise ValueError("加杠找不到原碰牌")
                        index, meld = matches[0]
                        consumed = _remove_exact(consumed, meld["tiles"])
                        choice.update(consumed=consumed, meldIndex=index, tile=consumed[0])
                    elif kind == 11:
                        if consumed or state["playerCount"] != 3:
                            raise ValueError("拔北组合不合法")
                        consumed = ["4z"]
                        choice.update(consumed=consumed, tile="4z")
                    elif kind == 10:
                        if consumed or len({tile_index(t) for t in hand}.intersection(ORPHANS)) < 9:
                            raise ValueError("九种九牌不完整")
                        choice["tile"] = None
                    _remove_exact(hand, consumed)
                    choice["actionId"] = ":".join([choice["action"], choice.get("calledTile", ""), *sorted(consumed)])
                    choices.append(choice)
                except (KeyError, IndexError, ValueError, TypeError):
                    warnings.append(f"{mapping[kind]} 组合未能核实，已略过")
    return list({c["actionId"]: c for c in choices}.values()), list(dict.fromkeys(warnings))


def _apply_choice(state, choice):
    next_ = deepcopy(state)
    seat, action = state["selfSeat"], choice["action"]
    next_["hand"] = _remove_exact(state["hand"], choice["consumed"])
    next_["lastDraw"] = None
    next_["forbiddenDiscards"] = []
    if action in ("chi", "pon", "daiminkan"):
        source = choice["fromSeat"]
        next_["rivers"][source][-1]["called"] = True
        next_["melds"][seat].append({"type": {"chi": 0, "pon": 1, "daiminkan": 2}[action],
                                      "tiles": choice["consumed"] + [choice["calledTile"]]})
        next_["forbiddenDiscards"] = [choice["calledTile"]]
        if action == "chi":
            indices = sorted(tile_index(t) for t in choice["consumed"] + [choice["calledTile"]])
            called = tile_index(choice["calledTile"])
            swap = indices[-1] + 1 if called == indices[0] else indices[0] - 1 if called == indices[-1] else -1
            if 0 <= swap < 27 and swap // 9 == called // 9:
                next_["forbiddenDiscards"].append(TILES[swap])
    elif action == "ankan":
        next_["melds"][seat].append({"type": 3, "tiles": choice["consumed"].copy()})
    elif action == "shouminkan":
        meld = next_["melds"][seat][choice["meldIndex"]]
        meld["type"] = 2
        meld["tiles"].extend(choice["consumed"])
    elif action == "kita":
        next_["north"][seat] += 1
    return next_


def _locked_risk(state, remaining, candidate, *, opportunities=None):
    """Compatibility view of the shared policy: riichi cannot choose to fold."""
    opponents = _opponents(state, remaining, after_current=True, passed_discard=candidate.get("tile"))
    if opportunities is None:
        opportunities = _opportunities(state, after_discard=True)
    hand = state["hand"].copy()
    if candidate.get("tile") in hand:
        hand.remove(candidate["tile"])
    outcome = _ready_policy(hand, state, remaining, opponents, opportunities,
                            candidate["winningTiles"], locked=True)[0]
    return outcome.scale(1 - candidate["dealInProbability"]).metrics()


def _abort_terminals(candidate):
    """A passed current discard ends the hand; no ordinary draw settlement."""
    candidate.update(terminalProbabilities={"selfWin": 0., "dealIn": candidate["dealInProbability"],
                                           "opponentTsumo": 0., "otherRon": 0., "exhaustiveDraw": 0.,
                                           "abortiveDraw": 1 - candidate["dealInProbability"]},
                     expectedOpponentTsumoLoss=0., expectedOtherRonLiabilityLoss=0.,
                     expectedDrawPayment=0., futureFoldProbability=0.,
                     futureDiscardDealInProbability=0., futureDiscardDealInLoss=0.,
                     futureForcedDealInProbability=0., futureForcedDealInLoss=0.)


def _riichi(state, choice, remaining):
    seat = state["selfSeat"]
    if (state.get("riichi", [False] * 4)[seat] or any(m["type"] != 3 for m in state["melds"][seat]) or
            state["scores"][seat] < 1000 or state["left"] < state["playerCount"]):
        raise ValueError("立直前提不完整")
    next_ = deepcopy(state)
    # This is a new declaration, not an already locked hand. A normal draw
    # clears temporary furiten; old discard-based waits must be recomputed for
    # the proposed discard before the hypothetical riichi flag locks them.
    if state.get("lastDraw") is not None:
        next_["furiten"] = False
    next_["riichi"][seat] = True
    next_.setdefault("doubleRiichi", [False] * 4)[seat] = bool(state.get("canDoubleRiichi"))
    hand = _remove_exact(state["hand"], [choice["tile"]])
    candidate = _position(hand, next_, remaining, choice["tile"])
    if candidate["shanten"] != 0 or not candidate["hasValidWait"]:
        raise ValueError("立直弃牌没有合法听口")
    # The new stick is our own money: recover it only if we win. Existing pot
    # remains in hand values; adding our stick as a free 1000-point prize is wrong.
    four_riichi = state["playerCount"] == 4 and all(next_["riichi"][:4])
    if four_riichi:
        candidate.update(winProbability=0., expectedWinPoints=0,
                         futureForcedDealInProbability=0., futureForcedDealInLoss=0,
                         score=-_risk_weight(state) * candidate["expectedDealInLoss"],
                         abortAfterRiichi=True, valueMethod="四家立直流局")
        _abort_terminals(candidate)
        _record_score(candidate, currentDealInLoss=-candidate["expectedDealInLoss"],
                      riskPreferenceAdjustment=-(_risk_weight(state) - 1) * candidate["expectedDealInLoss"])
        candidate["reasons"].append("第四家立直：宣言牌未被荣和则途中流局，无后续和牌机会或听牌料")
    deposit_loss = 1000 * max(0., 1 - candidate["dealInProbability"] - candidate["winProbability"])
    candidate["score"] = round(candidate["score"] - deposit_loss, 1)
    candidate.update(choice, riichiDeposit=1000, expectedRiichiCost=round(deposit_loss),
                     doubleRiichi=bool(state.get("canDoubleRiichi")))
    terms = dict(candidate["scoreBreakdown"])
    terms["riichiCost"] = -deposit_loss
    _record_score(candidate, **terms)
    candidate["reasons"].extend(["按两立直加役计分" if state.get("canDoubleRiichi") else "立直加役计分，与同张默听弃牌比较",
                                 "扣除未获胜时留在供托的 1000 点；未计一发与里宝牌",
                                 "四家立直后无后续摸切" if four_riichi else "立直后不能自由弃和，已折算后续强制摸切风险"])
    return candidate


def _draw_pool(state, remaining):
    known = list(state["hand"]) + list(state.get("doras", []))
    known += [d["tile"] for river in state["rivers"] for d in river]
    known += [t for melds in state["melds"] for meld in melds for t in meld["tiles"]]
    known_red = {t for t in known if t.startswith("0")}
    for i, count in enumerate(remaining):
        if not count:
            continue
        tile = TILES[i]
        red = int(i in (4, 13, 22) and (state["playerCount"] == 4 or i != 4) and "0" + tile[1] not in known_red)
        if count - red:
            yield tile, count - red
        if red:
            yield "0" + tile[1], red


def _replacement(state, choice, remaining):
    if state["left"] <= 0 or sum(remaining) == 0:
        raise ValueError("没有可用补牌机会")
    action = choice["action"]
    next_ = _apply_choice(state, choice)
    if unseen_counts(next_) != remaining:
        raise ValueError("动作后的实体牌计数不守恒")
    kans = [(owner, m) for owner, melds in enumerate(next_["melds"]) for m in melds if m["type"] in (2, 3)]
    if action != "kita" and len(kans) > 4:
        raise ValueError("不能进行第五杠")
    abort_after_discard = action != "kita" and len(kans) == 4 and len({owner for owner, _ in kans}) > 1
    next_["left"] = 0 if abort_after_discard else next_["left"] - 1
    next_["forbiddenDiscards"] = []
    outcomes = []
    for draw, weight in _draw_pool(next_, remaining):
        _check_search()
        drawn = deepcopy(next_)
        drawn["hand"].append(draw)
        drawn["lastDraw"] = draw
        unseen = list(remaining)
        unseen[tile_index(draw)] -= 1
        if min(unseen) < 0:
            raise ValueError("补牌后未见张数为负")
        drawn["replacementWin"] = True
        winning = _hand_value(next_["hand"], draw, drawn, True) if shanten(counts34(drawn["hand"]), not drawn["melds"][drawn["selfSeat"]]) == -1 else {"points": 0}
        if winning["points"]:
            best = {"shanten": -1, "ukeire": 0, "winProbability": 1., "expectedWinPoints": winning["points"],
                    "dealInProbability": 0., "expectedDealInLoss": 0., "score": winning["points"] + 420,
                    "tile": None, "furiten": False}
            best["terminalProbabilities"] = {"selfWin": 1., "dealIn": 0., "opponentTsumo": 0.,
                                              "otherRon": 0., "exhaustiveDraw": 0.}
            _record_score(best, winIncome=winning["points"], efficiencyReward=420)
        else:
            drawn["replacementWin"] = False
            legal = _discards(drawn, tuple(unseen))
            if not legal:
                raise ValueError("补牌后没有合法弃牌")
            if abort_after_discard:
                # Resolve the fourth-kan replacement win or discard ron first;
                # the ensuing abortive draw has neither future turns nor noten fees.
                for candidate in legal:
                    candidate.update(winProbability=0., expectedWinPoints=0,
                                     score=-_risk_weight(state) * candidate["expectedDealInLoss"])
                    _abort_terminals(candidate)
                    _record_score(candidate, currentDealInLoss=-candidate["expectedDealInLoss"],
                                  riskPreferenceAdjustment=-(_risk_weight(state) - 1) * candidate["expectedDealInLoss"])
            best = max(legal, key=lambda c: c["score"])
        outcomes.append((weight, best, draw))
    total = sum(w for w, _, _ in outcomes)
    mean = lambda field: sum(w * c[field] for w, c, _ in outcomes) / total
    opponents = _opponents(state, remaining)
    if action in ("shouminkan", "kita"):
        rob, rob_loss, risks = _danger(choice["tile"], remaining, opponents, chankan=action == "shouminkan")
    elif action == "ankan":
        # Only kokushi may rob an ankan; north robbery permits other yaku.
        applicable = tile_index(choice["tile"]) in ORPHANS
        risks = []
        for enemy in opponents:
            if not applicable or not enemy["canKokushi"] or tile_index(choice["tile"]) in enemy["safe"]:
                continue
            config = _config(state, seat=enemy["seat"])
            config.kyoutaku_number = 0
            risks.append({"seat": enemy["seat"], "probability": .0005 * enemy["tenpai"],
                          "lossPoints": _points(13, 0, config, state["playerCount"], yakuman=True),
                          "reason": "国士抢暗杠例外估计"})
        rob = min(1., sum(r["probability"] for r in risks))
        rob_loss = sum(r["probability"] * r["lossPoints"] for r in risks)
    else:
        rob, rob_loss, risks = 0., 0., []
    uncertainty = 0 if action == "kita" or abort_after_discard else 60 + 80 * sum(o["tenpai"] for o in opponents)
    loss = rob_loss + (1 - rob) * mean("expectedDealInLoss")
    danger = rob + (1 - rob) * mean("dealInProbability")
    probability = (1 - rob) * mean("winProbability")
    win_mass = sum(w * c["winProbability"] * c["expectedWinPoints"] for w, c, _ in outcomes)
    point_value = win_mass / sum(w * c["winProbability"] for w, c, _ in outcomes) if win_mass else 0
    reasons = ["按每种实际未见补牌的张数加权，补牌后再选择合法弃牌",
               "未见牌包含他家手牌与王牌，补牌概率为启发式估计"]
    if action != "kita":
        reasons.append("未预知新宝牌，不计其收益；已计入额外宝牌的不确定性")
    if action in ("shouminkan", "ankan", "kita"):
        reasons.append("抢北不限国士，按北牌危险度估计；不额外加入抢杠役" if action == "kita" else "抢杠风险单独估计，暗杠仅考虑国士例外")
    if abort_after_discard:
        reasons.append("第四杠涉及多家：仅计算补牌自摸与随后弃牌放铳，之后四杠散了，无听牌料")
    result = {**choice, "replacementDraw": True, "metricContext": "replacement", "shanten": round(sum(w * max(0, c["shanten"]) for w, c, _ in outcomes) / total, 2), "ukeire": round(mean("ukeire"), 1),
            "improvingTiles": [], "winningTiles": [], "hasValidWait": None, "furiten": all(c["furiten"] for _, c, _ in outcomes),
            "winProbability": round(probability, 4), "expectedWinPoints": round(point_value),
            "dealInProbability": round(danger, 4), "expectedDealInLoss": round(loss),
            "dealInPoints": round(loss / danger) if danger else 0, "dealInLossIfHit": round(loss / danger) if danger else 0,
            "score": round((1 - rob) * mean("score") - _risk_weight(state) * rob_loss - uncertainty, 1),
            "reasons": reasons, "opponentRisks": risks, "valueMethod": "补牌枚数加权估计", "newDoraRiskPenalty": round(uncertainty),
            "robKanProbability": round(rob, 4), "abortAfterDiscard": abort_after_discard, "replacementOutcomes": [
                {"draw": draw, "count": weight, "followupDiscard": c["tile"], "shanten": c["shanten"],
                 "winProbability": c["winProbability"]} for weight, c, draw in outcomes]}
    for field, digits in (("futureDiscardDealInProbability", 4), ("futureDiscardDealInLoss", 0),
                          ("futureForcedDealInProbability", 4), ("futureForcedDealInLoss", 0),
                          ("expectedOpponentTsumoLoss", 3), ("expectedOtherRonLiabilityLoss", 3),
                          ("expectedDrawPayment", 3), ("futureFoldProbability", 4)):
        result[field] = round((1 - rob) * sum(w * c.get(field, 0) for w, c, _ in outcomes) / total, digits)
    terminal_keys = {key for _, c, _ in outcomes for key in c.get("terminalProbabilities", {})}
    result["terminalProbabilities"] = {
        key: (1 - rob) * sum(w * c.get("terminalProbabilities", {}).get(key, 0) for w, c, _ in outcomes) / total
        for key in terminal_keys}
    result["terminalProbabilities"]["dealIn"] = result["terminalProbabilities"].get("dealIn", 0.) + rob
    fields = dict.fromkeys(key for _, candidate, _ in outcomes for key in candidate["scoreBreakdown"]
                           if key != "roundingAdjustment")
    terms = {key: (1 - rob) * sum(w * c["scoreBreakdown"].get(key, 0) for w, c, _ in outcomes) / total
             for key in fields}
    terms["currentDealInLoss"] = terms.get("currentDealInLoss", 0) - rob_loss
    terms["riskPreferenceAdjustment"] = terms.get("riskPreferenceAdjustment", 0) - (_risk_weight(state) - 1) * rob_loss
    terms["newDoraPenalty"] = -uncertainty
    _record_score(result, **terms)
    return result


def _advise(state):
    """Return JSON-safe action advice for one immutable public snapshot."""
    started = time.monotonic()

    def result(status, message, candidates=None, **extra):
        candidates = candidates or []
        return {"status": status, "message": message, "candidates": candidates,
                "best": candidates[0] if candidates else None, "model": MODEL,
                "elapsedMs": round((time.monotonic() - started) * 1000, 1), **extra}

    if state.get("phase") != "playing":
        return result("waiting", "等待进行中的牌局")
    if not state.get("handComplete") or not state.get("historyComplete"):
        return result("unavailable", "手牌或公开历史不完整，暂停推荐")
    operations = state.get("operations", [])
    can_act = state.get("canAct") is not False
    if can_act and (8 in operations or 9 in operations):
        return result("win", "当前可自摸和牌" if 8 in operations else "当前可荣和",
                      action="tsumo" if 8 in operations else "ron")
    discard_window = bool(can_act and state.get("canDiscard") and 1 in operations)
    own_seat = state.get("selfSeat")
    locked_optional = bool(can_act and isinstance(own_seat, int) and own_seat in range(state.get("playerCount", 0)) and
                           state.get("riichi", [False] * 4)[own_seat] and any(k in operations for k in (4, 11)))
    own_turn = discard_window or locked_optional
    reaction = can_act and any(k in operations for k in (2, 3, 5))
    analysis_only = not own_turn and not reaction
    if analysis_only and len(state.get("hand", [])) % 3 != 1:
        return result("waiting", "等待自己的合法操作窗口")
    try:
        seat, players = state["selfSeat"], state["playerCount"]
        if players not in (3, 4) or not isinstance(seat, int) or seat not in range(players):
            raise ValueError("座位或人数不完整")
        round_ = state.get("round") or {}
        if (not all(isinstance(round_.get(k), int) for k in ("chang", "ju", "ben")) or
                not 0 <= round_["ju"] < players or not 0 <= round_["chang"] < 4 or round_["ben"] < 0):
            raise ValueError("场风、自风或本场信息不完整")
        melds = state["melds"][seat]
        if len(state["hand"]) != (14 if own_turn else 13) - len(melds) * 3:
            raise ValueError("手牌张数与副露不一致")
        for meld in melds:
            if meld["type"] not in (0, 1, 2, 3) or len(meld["tiles"]) != (3 if meld["type"] < 2 else 4):
                raise ValueError("副露结构不完整")
        left = state.get("left")
        if not isinstance(left, int) or left < 0:
            raise ValueError("剩余牌山信息不完整")
        remaining = unseen_counts(state)
        candidates = _discards(state, remaining) if own_turn else [_position(state["hand"], state, remaining)]
        if not candidates:
            raise ValueError("没有已确认合法的弃牌")
        opportunities = _opportunities(state, after_discard=own_turn)
        if locked_optional and not discard_window:
            for candidate in candidates:
                candidate.update(action="pass", actionId="pass", followupDiscard=candidate["tile"], metricContext="followup")
                candidate["tile"] = None
                candidate["reasons"].append("跳过本次动作后立直状态只能摸切，已评估该摸切牌")
        if analysis_only:
            candidates[0].update(action="wait", actionId="wait", metricContext="hand")
            candidates[0]["reasons"].append("当前无可执行操作；评估现有手牌，等待下次合法窗口")
        elif not own_turn:
            candidates[0]["reasons"].append("跳过当前鸣牌，保留手牌与门清状态")
        choices, warnings = ([], []) if analysis_only else _action_choices(state)
        for choice in choices:
            try:
                action = choice["action"]
                if action == "riichi" and own_turn:
                    candidates.append(_riichi(state, choice, remaining))
                elif action in ("chi", "pon") and not own_turn:
                    next_ = _apply_choice(state, choice)
                    if unseen_counts(next_) != remaining:
                        raise ValueError("鸣牌后的实体牌计数不守恒")
                    options = _discards(next_, remaining)
                    if not options:
                        raise ValueError("鸣牌后没有合法弃牌")
                    best = max(options, key=lambda c: c["score"])
                    best["followupDiscard"] = best["tile"]
                    best["metricContext"] = "followup"
                    best.update(choice)
                    # A small shape gain alone must not encourage opening a
                    # hand whose plausible yaku was destroyed by the call.
                    if best["yakuConfidence"] < 1 or (best["shanten"] == 0 and
                            not any(w["ronPoints"] or w["tsumoPoints"] for w in best["winningTiles"])):
                        best["score"] = round(best["score"] - 500, 1)
                        _record_score(best, **best["scoreBreakdown"], openNoYakuPenalty=-500)
                        best["reasons"].append("鸣牌破坏门清且缺少可确认役，另计无役路线代价")
                    best["reasons"].append("已比较鸣牌后的合法弃牌，排除同牌及筋食替")
                    candidates.append(best)
                elif action in ("ankan", "shouminkan", "kita") and own_turn or action == "daiminkan" and not own_turn:
                    candidates.append(_replacement(state, choice, remaining))
                elif action == "abort" and own_turn:
                    # No current-hand transfer; normalize comparison below
                    # after every server-offered continuation has been evaluated.
                    candidates.append({**choice, "shanten": None, "ukeire": 0, "improvingTiles": [], "winningTiles": [],
                                       "hasValidWait": None, "furiten": False, "winProbability": 0., "expectedWinPoints": 0,
                                       "dealInProbability": 0., "expectedDealInLoss": 0, "dealInPoints": 0, "dealInLossIfHit": 0,
                                       "score": 0., "reasons": ["九种九牌结束本局，无本局点数收支；连庄及排名后续价值未建模"],
                                       "opponentRisks": [], "valueMethod": "本局零收支基线"})
                    _abort_terminals(candidates[-1])
                    _record_score(candidates[-1])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                warnings.append(f"{choice['action']} 暂不推荐：{exc}")
        if any(c["action"] == "abort" for c in candidates):
            # All continuations already contain the same terminal payments.
            # Remove shape/yaku preferences, not the shared survival ledger.
            for candidate in candidates:
                if candidate["action"] == "abort":
                    continue
                terms = {k: v for k, v in candidate["scoreBreakdown"].items()
                         if k not in ("efficiencyReward", "openNoYakuPenalty", "roundingAdjustment")}
                candidate["score"] = round(fsum(terms.values()), 1)
                _record_score(candidate, **terms)
                candidate["reasons"].append("与九种九牌按同一本局终局账目比较，移除形状奖励，保留自摸损失和流局收支")
        candidates.sort(key=lambda c: (-c["score"], c["shanten"] if c["shanten"] is not None else 99,
                                       -c["ukeire"], (c.get("tile") or "").startswith("0"), c["actionId"]))
        return result("analysis" if analysis_only else "ready",
                      "等待下一次行动 · 当前手牌评估" if analysis_only else "综合动作推荐（概率为未校准估计）", candidates,
                      riskWeight=_risk_weight(state), rankContext=_rank_context(state), unseenTileCount=sum(remaining),
                      remainingOwnDraws=opportunities.count(seat),
                      warnings=list(dict.fromkeys(warnings)),
                      assumptions=["未见牌包含对手手牌与王牌，并非实际牌山余张",
                                   "按普通三麻/四麻规则，未解析自定义规则",
                                   "综合分综合和牌估值、放铳损失、效率与流局听牌收益",
                                   "仅比较服务端许可的动作组合；立直计供托代价及后续摸切风险",
                                   "补牌按未见张数加权；新宝牌、一发、里宝牌和排名后续价值未精确建模",
                                   "振听结合弃牌历史与服务端标志；可和牌操作以游戏为准",
                                   "概率未经实战校准，非保证最优或真实胜率"])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return result("unavailable", f"牌局状态无法可靠计算：{exc}")


class _SearchStopped(Exception):
    pass


def _check_search():
    search = _SEARCH.get()
    if search is not None:
        deadline, cancelled = search
        if cancelled is not None and cancelled():
            raise _SearchStopped("局面已更新，撤销过期计算")
        if time.monotonic() >= deadline:
            raise _SearchStopped("前瞻计算超过时间预算，等待下一次局面")


def advise(state, cancelled=None):
    """Publish only a complete, uniformly evaluated decision within the budget."""
    started = time.monotonic()
    token = _SEARCH.set((started + SEARCH_SECONDS, cancelled))
    values_token = _HAND_VALUES.set({})
    policy_token = _POLICY_RISKS.set({})
    tables_token = TABLES.set({})
    try:
        _check_search()
        result = _advise(state)
        _check_search()
        return result
    except _SearchStopped as error:
        return {"status": "unavailable", "message": str(error), "candidates": [],
                "best": None, "model": MODEL, "elapsedMs": round((time.monotonic() - started) * 1000, 1)}
    finally:
        TABLES.reset(tables_token)
        _POLICY_RISKS.reset(policy_token)
        _HAND_VALUES.reset(values_token)
        _SEARCH.reset(token)
