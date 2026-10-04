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


MODEL = "public-information-actions-ev-v4 (未校准启发式)"
SEARCH_SECONDS = 2.
_SEARCH = ContextVar("advisor_search", default=None)
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
    melds = [Meld(Meld.CHI if m["type"] == 0 else Meld.PON if m["type"] == 1 else Meld.KAN,
                  ids[n + 1], opened=m["type"] != 3)
             for n, m in enumerate(meld_data)]
    # A kan encoded as four ordinary fives carries no known aka information.
    # Avoid assigning an invented red bonus merely because IDs require slot 0.
    implicit_red = sum(i in (16, 52, 88) and t[0] != "0"
                       for group, values in zip(all_groups, ids) for t, i in zip(group, values))
    return [i for group in ids for i in group], ids[0][-1], melds, implicit_red


def _hand_value(concealed, winning_tile, state, tsumo):
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


def _opponents(state, remaining):
    opponents = []
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
                        if step < d.get("step", -1) < state.get("lastStep", -1))
        open_melds = [m for m in melds if m["type"] != 3]
        turn = len(river)
        tenpai = 1.0 if riichi else min(.65, .04 + turn * .018 + len(open_melds) * .14)
        cfg = _config(state, seat=enemy)
        cfg.kyoutaku_number = 0  # Existing deposits are not paid by the discarder.
        visible = [t for m in melds for t in m["tiles"]]
        visible_counts = counts34(visible)
        yakuhai = sum(visible_counts[i] >= 3 for i in (31, 32, 33, cfg.player_wind, cfg.round_wind))
        han = (3 if riichi else max(1, yakuhai)) + sum(visible_counts[i] for i in dora)
        han += sum(t[0] == "0" for t in visible)
        han += state.get("north", [0] * 4)[enemy] * (1 + dora.count(30))
        loss = _points(han, 40 if riichi or not open_melds else 30, cfg, players)
        opponents.append({"seat": enemy, "safe": safe, "tenpai": tenpai,
                          "loss": loss, "riichi": riichi, "dora": dora,
                          "canKokushi": not melds})
    return opponents


def _danger(tile, remaining, opponents):
    index = tile_index(tile)
    survival, expected_loss, details = 1., 0., []
    for enemy in opponents:
        if index in enemy["safe"]:
            chance = 0.
            reason = "现物"
        elif index >= 27:
            # No unseen honor blocks pair/triplet waits, but a closed hand can
            # still win kokushi on a missing singleton honor.
            chance = ((.001 if enemy["canKokushi"] else 0.), .025, .065, .10, .12)[remaining[index]] * enemy["tenpai"]
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
            chance = shape * enemy["tenpai"]
            reason = "筋（仍可能放铳）" if suji else "无安全依据"
        if index in enemy["dora"] and chance:
            chance *= 1.2
        survival *= 1 - chance
        expected_loss += chance * enemy["loss"]
        details.append({"seat": enemy["seat"], "probability": round(chance, 4),
                        "lossPoints": enemy["loss"], "reason": reason})
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
                options.append({"discard": tile, "waits": waits, "furiten": furiten})
        branches.append({"draw": draw, "count": weight, "remaining": tuple(unseen), "options": options})
    return branches


def _one_shanten_model(branches, unseen, opponents, opportunities, own_seat):
    """First effective draw without replacement, followed by the actual suffix.

    If H+A-X waits on B, H+B-X waits on A. Thus live waits are effective
    families already: preceding ineffective tsumogiri cannot deplete them or
    make them furiten. Only their total unknown mass needs tracking here.
    Opponents and the later ready-hand pool still use the public-info heuristic.
    """
    effective = sum(branch["count"] for branch in branches)
    live, misses = 1., 0
    wins, incomes = [], []
    survival = _event_survival(opponents)
    for index, actor in enumerate(opportunities):
        _check_search()
        if actor == own_seat:
            pool = unseen - misses
            if pool <= 0 or live == 0:
                break
            for branch in sorted(branches, key=lambda b: b["draw"]):
                outcomes = []
                for option in sorted(branch["options"], key=lambda o: o["discard"]):
                    probability, value = _win_model(
                        0, sum(w["count"] for w in option["waits"]), pool - 1, 0,
                        opponents, option["waits"], opportunities=opportunities[index + 1:], own_seat=own_seat)
                    outcomes.append((probability * value, probability, value))
                income, probability, _ = max(outcomes, default=(0., 0., 0.))
                mass = live * branch["count"] / pool * survival
                wins.append(mass * probability)
                incomes.append(mass * income)
            live *= max(0., 1 - effective / pool)
            misses += 1
        live *= survival
    probability = fsum(wins)
    return probability, fsum(incomes) / probability if probability else 0.


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


def _risk_weight(state):
    players, seat = state["playerCount"], state["selfSeat"]
    scores = state.get("scores", [])
    weight = 1.15
    if len(scores) >= players:
        rivals = [scores[i] for i in range(players) if i != seat]
        weight += .3 if scores[seat] - max(rivals) >= 8000 else 0
        weight -= .15 if scores[seat] < min(rivals) else 0
        weight += .2 if scores[seat] < 8000 else 0
    return weight


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
    if sh == 1:
        branches = _one_shanten_branches(hand, counts, improvements, remaining, state, discard, special)
        probability, value = _one_shanten_model(branches, unseen, opponents, opportunities, state["selfSeat"])
        yaku_factor = float(any(w["ronPoints"] or w["tsumoPoints"]
                               for b in branches for o in b["options"] for w in o["waits"]))
    else:
        probability, ready_value = _win_model(sh, ukeire, unseen, draws, opponents, waits,
                                             yaku_factor=yaku_factor,
                                             opportunities=opportunities, own_seat=state["selfSeat"])
        if kokushi_route:
            probability = _kokushi_probability(counts, remaining, draws, opponents, state, discard, 0, opportunities)
        if waits is not None:
            value = ready_value
    probability *= 1 - danger
    reasons = [f"{'听牌' if sh == 0 else str(sh) + ' 向听'}；有效未见牌 {ukeire} 张"]
    if sh == 0 and not waits:
        reasons[0] = "形式 0 向听，但没有实体上合法的听口"
    if furiten:
        reasons.append("整副牌振听，所有等待均只估自摸")
    if sh == 0 and not any(w["ronPoints"] or w["tsumoPoints"] for w in waits):
        reasons.append("当前等待无役，不能仅凭宝牌和牌")
    if detail and all(d["probability"] == 0 for d in detail):
        reasons.append("对各家均有现物或字牌枚数安全依据")
    elif any(o["riichi"] for o in opponents):
        reasons.append("有对手立直，已计入较高放铳风险")
    if discard and discard[0] == "0":
        reasons.append("打出赤宝牌，打点下降")
    if yaku_factor != 1 and sh:
        reasons.append("一向听前瞻未找到有役等待" if sh == 1 else "副露后役尚未确定，和牌前景已折减")
    if kokushi_route:
        reasons.append("国士路线按缺少幺九及雀头估计推进")
    efficiency = 70 * (6 - sh) + 2 * ukeire
    tenpai_bonus = ((1500 if state["playerCount"] == 4 else 1000) *
                    max(0., 1 - state["left"] / 28)) if sh == 0 and waits else 0
    score = probability * value - _risk_weight(state) * loss + efficiency + tenpai_bonus
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
    if branches is not None:
        result["lookahead"] = {"drawVariants": len(branches),
                               "readyDiscards": sum(len(b["options"]) for b in branches)}
        reasons.append("完整枚举有效进张及后续弃牌；逐分支计役与点值，保留未进张概率")
    elif sh >= 2:
        reasons.append("二向听以上仍使用未来进张与打点估算")
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


def _locked_risk(state, remaining, candidate):
    """Expected future forced discards, bounded by competition and winning.

    Dama can fold; this is a conservative cost of surrendering that option.
    It is separate from the declaration tile's immediate deal-in probability.
    """
    unseen = sum(remaining)
    opponents = _opponents(state, remaining)
    winning = {tile_index(w["tile"]) for w in candidate["winningTiles"] if w["tsumoPoints"]}
    average_loss = sum(n * _danger(TILES[i], remaining, opponents)[1]
                       for i, n in enumerate(remaining) if n and i not in winning) / max(1, unseen)
    survival = _event_survival(opponents)
    hit = sum(n for i, n in enumerate(remaining) if i in winning) / max(1, unseen)
    ron = min(.65, sum(w["count"] for w in candidate["winningTiles"] if w["ronPoints"]) / max(1, unseen) * .45)
    live, loss, turns = 1., 0., 0
    for actor in _opportunities(state, after_discard=True):
        if actor == state["selfSeat"]:
            loss += live * average_loss
            turns += 1
            if turns == 12:
                break
        live *= (1 - (hit if actor == state["selfSeat"] else ron)) * survival
    return loss * (1 - candidate["dealInProbability"])


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
                         score=-_risk_weight(state) * candidate["expectedDealInLoss"],
                         abortAfterRiichi=True, valueMethod="四家立直流局")
        candidate["reasons"].append("第四家立直：宣言牌未被荣和则途中流局，无后续和牌机会或听牌料")
    deposit_loss = 1000 * max(0., 1 - candidate["dealInProbability"] - candidate["winProbability"])
    locked_loss = 0 if four_riichi else _locked_risk(next_, remaining, candidate)
    candidate["score"] = round(candidate["score"] - deposit_loss - _risk_weight(state) * locked_loss, 1)
    candidate.update(choice, riichiDeposit=1000, expectedRiichiCost=round(deposit_loss),
                     futureForcedDealInLoss=round(locked_loss), doubleRiichi=bool(state.get("canDoubleRiichi")))
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
            best = max(legal, key=lambda c: c["score"])
        outcomes.append((weight, best, draw))
    total = sum(w for w, _, _ in outcomes)
    mean = lambda field: sum(w * c[field] for w, c, _ in outcomes) / total
    opponents = _opponents(state, remaining)
    if action in ("shouminkan", "kita"):
        rob, rob_loss, risks = _danger(choice["tile"], remaining, opponents)
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
    return {**choice, "replacementDraw": True, "metricContext": "replacement", "shanten": round(sum(w * max(0, c["shanten"]) for w, c, _ in outcomes) / total, 2), "ukeire": round(mean("ukeire"), 1),
            "improvingTiles": [], "winningTiles": [], "hasValidWait": None, "furiten": all(c["furiten"] for _, c, _ in outcomes),
            "winProbability": round(probability, 4), "expectedWinPoints": round(point_value),
            "dealInProbability": round(danger, 4), "expectedDealInLoss": round(loss),
            "dealInPoints": round(loss / danger) if danger else 0, "dealInLossIfHit": round(loss / danger) if danger else 0,
            "score": round((1 - rob) * mean("score") - _risk_weight(state) * rob_loss - uncertainty, 1),
            "reasons": reasons, "opponentRisks": risks, "valueMethod": "补牌枚数加权估计", "newDoraRiskPenalty": round(uncertainty),
            "robKanProbability": round(rob, 4), "abortAfterDiscard": abort_after_discard, "replacementOutcomes": [
                {"draw": draw, "count": weight, "followupDiscard": c["tile"], "shanten": c["shanten"],
                 "winProbability": c["winProbability"]} for weight, c, draw in outcomes]}


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
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                warnings.append(f"{choice['action']} 暂不推荐：{exc}")
        if any(c["action"] == "abort" for c in candidates):
            # Use point values for every continuation when comparing with a
            # zero-transfer abort, rather than awarding only play shape points.
            opponents = _opponents(state, remaining)
            background_loss = ((1 - _event_survival(opponents) ** len(opportunities)) * .4 *
                               sum(o["loss"] for o in opponents) / max(1, len(opponents)) / (players - 1))
            for candidate in candidates:
                if candidate["action"] == "abort":
                    continue
                continuation_loss = background_loss * (1 - candidate["winProbability"])
                candidate["score"] = round(candidate["winProbability"] * candidate["expectedWinPoints"] -
                                           _risk_weight(state) * (candidate["expectedDealInLoss"] + candidate.get("futureForcedDealInLoss", 0)) -
                                           candidate.get("expectedRiichiCost", 0) - candidate.get("newDoraRiskPenalty", 0) - continuation_loss, 1)
                candidate["reasons"].append("与九种九牌按本局点数比较，移除形状奖励；继续牌局的他家自摸损失仅作启发式折减")
        candidates.sort(key=lambda c: (-c["score"], c["shanten"] if c["shanten"] is not None else 99,
                                       -c["ukeire"], (c.get("tile") or "").startswith("0"), c["actionId"]))
        return result("analysis" if analysis_only else "ready",
                      "等待下一次行动 · 当前手牌评估" if analysis_only else "综合动作推荐（概率为未校准估计）", candidates,
                      riskWeight=_risk_weight(state), unseenTileCount=sum(remaining),
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
    try:
        _check_search()
        result = _advise(state)
        _check_search()
        return result
    except _SearchStopped as error:
        return {"status": "unavailable", "message": str(error), "candidates": [],
                "best": None, "model": MODEL, "elapsedMs": round((time.monotonic() - started) * 1000, 1)}
    finally:
        _SEARCH.reset(token)
