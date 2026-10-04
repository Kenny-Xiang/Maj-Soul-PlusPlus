"""Bounded, public-information riichi discard advice.

Shanten, visible-tile counts and complete-hand scoring are rule calculations.
Win/deal-in probabilities and future values are deliberately *uncalibrated*
estimates, not a solved game or a claim about opponents' hidden tiles. Unseen
tiles include opponents' hands and the dead wall; they are never called live
wall tiles. The engine neither sends game actions nor assumes a future riichi.
"""
from functools import lru_cache
import time

from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.hand_calculating.scores import ScoresCalculator
from mahjong.meld import Meld
from mahjong.shanten import Shanten


MODEL = "public-information-ev-v1 (未校准启发式)"
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


def _win_model(sh, ukeire, unseen, draws, opponents, waits, projected=None, yaku_factor=1., tail=0):
    if not unseen or not ukeire:
        return 0., 0.
    # Background hazard represents opponents progressing beyond their currently
    # observed shapes; an early quiet table is not assumed quiet for 18 turns.
    competition = min(.22, .025 + sum(o["tenpai"] for o in opponents) * .04)
    if waits is not None:
        tsumo_mass = sum(w["count"] for w in waits if w["tsumoPoints"])
        ron_mass = sum(w["count"] for w in waits if w["ronPoints"])
        pt = tsumo_mass / unseen
        pr = min(.65, ron_mass / unseen * len(opponents) * .45)
        point_weight = sum(w["count"] * w["tsumoPoints"] for w in waits) / unseen
        point_weight += sum(w["count"] * w["ronPoints"] for w in waits) / unseen * len(opponents) * .45 * (1 - pt)
        hit = pt + (1 - pt) * pr
        live, win, ev = 1., 0., 0.
        for _ in range(draws):
            win += live * hit
            ev += live * point_weight
            live *= (1 - hit) * (1 - competition)
        # Fewer than a full cycle can still contain opponent discards, even
        # though the player will get no further draw before an exhaustive draw.
        for _ in range(tail):
            ron_hit = min(.65, ron_mass / unseen * .45)
            win += live * ron_hit
            ev += live * sum(w["count"] * w["ronPoints"] for w in waits) / unseen * .45
            live *= (1 - ron_hit) * (1 - competition / max(1, len(opponents)))
        value = ev / win if win else point_weight / hit if hit else 0.
        return min(1., win), value
    # A small absorbing Markov chain needs sh+1 effective draws. Later-stage
    # ukeire is projected; it is not held equal to the current wide ukeire.
    final_waits = projected if projected is not None else 6.
    rates = [min(.9, (min(32, ukeire) if k == 0 else
                     max(final_waits, min(16 * .60 ** (k - 1), ukeire * .60 ** k))) / unseen)
             for k in range(sh)] + [min(.8, final_waits / unseen * (1 + .45 * len(opponents)))]
    active = [1.] + [0.] * sh
    win = 0.
    for _ in range(draws):
        next_ = [0.] * len(active)
        for stage, mass in enumerate(active):
            hit = mass * rates[stage]
            if stage == sh:
                win += hit * yaku_factor
            else:
                next_[stage + 1] += hit * (1 - competition)
            next_[stage] += mass * (1 - rates[stage]) * (1 - competition)
        active = next_
    if tail:
        win += active[-1] * (1 - (1 - min(.8, final_waits / unseen * .45)) ** tail) * yaku_factor
    return min(1., win), 0.


def _next_waits(counts, improvements, remaining, special):
    """Bounded one-shanten lookahead, at most four effective draw types."""
    weight = total = 0.
    for improvement in sorted(improvements, key=lambda d: -d["count"])[:4]:
        index = tile_index(improvement["tile"])
        drawn = list(counts)
        drawn[index] += 1
        unseen = list(remaining)
        unseen[index] -= 1
        best = 0
        for discard, count in enumerate(drawn):
            if not count:
                continue
            trial = drawn.copy()
            trial[discard] -= 1
            trial = tuple(trial)
            if shanten(trial, special) == 0:
                best = max(best, sum(t["count"] for t in _improvements(trial, unseen, special)))
        weight += improvement["count"] * best
        total += improvement["count"]
    return weight / total if total else 0.


def _kokushi_probability(counts, remaining, draws, opponents, state, discard, tail):
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
    own_river.add(tile_index(discard))
    competition = min(.22, .025 + sum(o["tenpai"] for o in opponents) * .04)
    win = 0.

    def ron_probability(mask, pair, opportunities):
        if pair and mask.bit_count() == 1:
            waits = [missing[k] for k in range(len(missing)) if mask & (1 << k)]
        elif not pair and mask == 0:
            waits = list(ORPHANS)
        else:
            return 0.
        if own_river.intersection(waits):
            return 0.
        mass = sum(remaining[i] - int(i in missing and not mask & (1 << missing.index(i))) for i in waits)
        return min(.65, max(0, mass) / unseen * .45 * opportunities)

    for _ in range(draws):
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
        active = {}
        for (mask, pair), mass in next_.items():
            ron = ron_probability(mask, pair, len(opponents))
            win += mass * ron
            active[(mask, pair)] = mass * (1 - ron) * (1 - competition)
    for (mask, pair), mass in active.items():
        win += mass * ron_probability(mask, pair, tail)
    return min(1., win)


def advise(state):
    """Return JSON-safe advice for one immutable state snapshot."""
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
    if 8 in operations or 9 in operations:
        return result("win", "当前可自摸和牌" if 8 in operations else "当前可荣和",
                      action="tsumo" if 8 in operations else "ron")
    if not state.get("canDiscard") or 1 not in operations:
        return result("waiting", "等待自己的合法出牌窗口")
    try:
        seat, players = state["selfSeat"], state["playerCount"]
        if players not in (3, 4) or not isinstance(seat, int) or seat not in range(players):
            raise ValueError("座位或人数不完整")
        round_ = state.get("round") or {}
        if (not all(isinstance(round_.get(k), int) for k in ("chang", "ju", "ben")) or
                not 0 <= round_["ju"] < players or not 0 <= round_["chang"] < 4 or round_["ben"] < 0):
            raise ValueError("场风、自风或本场信息不完整")
        hand = list(state["hand"])
        melds = state["melds"][seat]
        if len(hand) != 14 - len(melds) * 3:
            raise ValueError("手牌张数与副露不一致")
        for meld in melds:
            if meld["type"] not in (0, 1, 2, 3) or len(meld["tiles"]) != (3 if meld["type"] < 2 else 4):
                raise ValueError("副露结构不完整")
        remaining = unseen_counts(state)
        special = not melds
        prohibited = {tile_index(t) for t in state.get("forbiddenDiscards", [])}
        legal = [t for t in dict.fromkeys(hand) if tile_index(t) not in prohibited]
        if state.get("riichi", [False] * 4)[seat]:
            draw = state.get("lastDraw")
            if draw not in legal:
                return result("unavailable", "立直后摸切牌不明确，暂停推荐")
            legal = [draw]
        if not legal:
            return result("unavailable", "没有已确认合法的弃牌")
        opponents = _opponents(state, remaining)
        left = state.get("left")
        if not isinstance(left, int) or left < 0:
            raise ValueError("剩余牌山信息不完整")
        draws = min(24, left // players)
        tail = left % players
        unseen = sum(remaining)
        scores = state.get("scores", [])
        risk_weight = 1.15
        if len(scores) >= players:
            rivals = [scores[i] for i in range(players) if i != seat]
            if scores[seat] - max(rivals) >= 8000:
                risk_weight += .3
            if scores[seat] < min(rivals):
                risk_weight -= .15
            if scores[seat] < 8000:
                risk_weight += .2
        candidates = []
        for tile in legal:
            after = hand.copy()
            after.remove(tile)
            counts = counts34(after)
            sh = shanten(counts, special)
            improvements = _improvements(counts, remaining, special)
            ukeire = sum(t["count"] for t in improvements)
            danger, loss, detail = _danger(tile, remaining, opponents)
            waits, furiten = _wait_values(after, counts, remaining, state, tile, special) if sh == 0 else (None, False)
            value, yaku_factor = _future_value(after, state, counts, special)
            probability, ready_value = _win_model(sh, ukeire, unseen, draws, opponents, waits,
                                                  yaku_factor=yaku_factor, tail=tail)
            kokushi_route = special and 0 < sh <= 2 and Shanten.calculate_shanten_for_kokushi_hand(counts) == sh
            if kokushi_route:
                probability = _kokushi_probability(counts, remaining, draws, opponents, state, tile, tail)
            probability *= 1 - danger
            if waits is not None:
                value = ready_value
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
            if tile[0] == "0":
                reasons.append("打出赤宝牌，打点下降")
            if not yaku_factor == 1 and sh:
                reasons.append("副露后役尚未确定，和牌前景已折减")
            if kokushi_route:
                reasons.append("国士路线按缺少幺九及雀头估计推进")
            efficiency = 70 * (6 - sh) + 2 * ukeire
            tenpai_bonus = (1500 if players == 4 else 1000) * max(0., 1 - left / 28) if sh == 0 and waits else 0
            score = probability * value - risk_weight * loss + efficiency + tenpai_bonus
            candidates.append({"tile": tile, "shanten": sh, "ukeire": ukeire,
                               "improvingTiles": improvements, "winningTiles": waits or [],
                               "hasValidWait": bool(waits) if sh == 0 else None,
                               "furiten": furiten, "winProbability": round(probability, 4),
                               "expectedWinPoints": round(value), "dealInProbability": round(danger, 4),
                               "expectedDealInLoss": round(loss),
                               "dealInPoints": round(loss / danger) if danger else 0,
                               "dealInLossIfHit": round(loss / danger) if danger else 0,
                               "score": round(score, 1), "reasons": reasons,
                               "opponentRisks": detail, "valueMethod": "听牌逐张计分" if sh == 0 else "未来牌型估值"})
        # Refine only leading one-shanten alternatives. All legal discards still
        # receive exact current shanten and ukeire; this bounded search is a tie
        # breaker, not an exhaustive multi-step policy search.
        leading = sorted(candidates, key=lambda c: -c["score"])
        for candidate in leading[:3]:
            if candidate["shanten"] != 1:
                continue
            after = hand.copy()
            after.remove(candidate["tile"])
            if special and Shanten.calculate_shanten_for_kokushi_hand(counts34(after)) == 1:
                continue
            projected = _next_waits(counts34(after), candidate["improvingTiles"], remaining, special)
            _, yaku_factor = _future_value(after, state, counts34(after), special)
            probability, _ = _win_model(1, candidate["ukeire"], unseen, draws, opponents, None,
                                        projected=projected, yaku_factor=yaku_factor, tail=tail)
            probability *= 1 - candidate["dealInProbability"]
            candidate["score"] = round(candidate["score"] + (probability - candidate["winProbability"]) * candidate["expectedWinPoints"], 1)
            candidate["winProbability"] = round(probability, 4)
            candidate["nextWaitEstimate"] = round(projected, 1)
            candidate["reasons"].append(f"推进后等待枚数估计 {projected:.1f}（限量前瞻）")
        candidates.sort(key=lambda c: (-c["score"], c["shanten"], -c["ukeire"], c["tile"].startswith("0"), tile_index(c["tile"])))
        return result("ready", "综合推荐（概率为未校准估计）", candidates,
                      riskWeight=risk_weight, unseenTileCount=unseen, remainingOwnDraws=draws,
                      assumptions=["未见牌包含对手手牌与王牌，并非实际牌山余张",
                                   "按普通三麻/四麻规则，未解析自定义规则",
                                   "综合分综合和牌估值、当前放铳损失、效率与流局听牌收益",
                                   "不读取暗牌；不包含未来立直、一发、里宝牌与特殊结算",
                                   "振听结合弃牌历史与服务端标志；可和牌操作以游戏为准",
                                   "概率未经实战校准，非保证最优或真实胜率"])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return result("unavailable", f"牌局状态无法可靠计算：{exc}")
