"""Nearest physically feasible open-hand targets for explicit yaku routes.

Templates describe complete concealed tiles with existing melds fixed. They
are construction witnesses, not probabilities or guarantees that a draw can
reach them. One nearest target is retained per value honor or toitoi pair;
equal-overlap choices use tile order deterministically, without future data.
"""
from functools import lru_cache
from itertools import combinations, combinations_with_replacement


def _index(tile):
    rank = 5 if tile[0] == "0" else int(tile[0])
    return "mpsz".index(tile[1]) * 9 + rank - 1


@lru_cache(maxsize=None)
def _patterns(width, groups, pair, suited):
    """All distinct local targets for a bounded number of sets and a pair."""
    sets = [tuple(3 if i == j else 0 for i in range(width)) for j in range(width)]
    if suited:
        sets += [tuple(int(j <= i <= j + 2) for i in range(width))
                 for j in range(width - 2)]
    patterns = set()
    for chosen in combinations_with_replacement(sets, groups):
        counts = tuple(sum(group[i] for group in chosen) for i in range(width))
        if max(counts, default=0) > 4:
            continue
        for index in range(width) if pair else (None,):
            target = tuple(n + (2 if i == index else 0) for i, n in enumerate(counts))
            if max(target, default=0) <= 4:
                patterns.add(target)
    return tuple((target, tuple((i, n) for i, n in enumerate(target) if n))
                 for target in sorted(patterns))


@lru_cache(maxsize=8192)
def _local_choices(counts, available, max_groups, suited):
    choices = []
    for groups in range(max_groups + 1):
        for pair in (0, 1):
            best = None
            for target, occupied in _patterns(len(counts), groups, pair, suited):
                if any(n > available[i] for i, n in occupied):
                    continue
                retained = sum(min(counts[i], n) for i, n in occupied)
                if best is None or retained > best[0]:
                    best = retained, target
            if best is not None:
                choices.append((groups, pair, *best))
    return tuple(choices)


def _regular_target(counts, available, groups):
    """Exact maximum retained tiles for sets plus a pair, by suit DP."""
    states = {(0, 0): (0, ())}
    for start, stop in ((0, 9), (9, 18), (18, 27), (27, 34)):
        options = _local_choices(counts[start:stop], available[start:stop], groups, start < 27)
        next_ = {}
        for (used_groups, used_pair), (retained, prefix) in states.items():
            for local_groups, local_pair, local_retained, target in options:
                key = used_groups + local_groups, used_pair + local_pair
                if key[0] > groups or key[1] > 1:
                    continue
                total = retained + local_retained
                if key not in next_ or total > next_[key][0]:
                    next_[key] = total, prefix + target
        states = next_
    return states.get((groups, 1), (None, None))[1]


def route_targets(counts, remaining, melds, value_honors):
    """Return concrete toitoi and value-honor targets, with existing melds fixed.

    Missing tiles must exist in the public unseen pool. The nearest target
    maximizes tiles retained from the current concealed hand; its shanten is
    sum(target) - 1 - sum(min(held, needed)). No yaku prior is involved.
    """
    groups = 4 - len(melds)
    fixed = [0] * 34
    for meld in melds:
        for tile in meld["tiles"]:
            fixed[_index(tile)] += 1
    available = tuple(min(counts[i] + remaining[i], 4 - fixed[i]) for i in range(34))
    targets = []
    if all(meld["type"] != 0 for meld in melds):
        for pair in range(34):
            if available[pair] < 2:
                continue
            triplets = sorted((i for i in range(34) if i != pair and available[i] >= 3),
                              key=lambda i: (-min(3, counts[i]), i))
            if len(triplets) < groups:
                continue
            target = [0] * 34
            target[pair] = 2
            for index in triplets[:groups]:
                target[index] = 3
            targets.append(("toitoi", tuple(target)))
    if groups:
        for honor in sorted(set(value_honors)):
            if not 27 <= honor < 34 or available[honor] < 3:
                continue
            held = list(counts)
            held[honor] = max(0, held[honor] - 3)
            stock = list(available)
            stock[honor] -= 3
            target = _regular_target(tuple(held), tuple(stock), groups - 1)
            if target is not None:
                target = list(target)
                target[honor] += 3
                targets.append((f"yakuhai:{honor}", tuple(target)))
    return targets


def seven_pair_targets(counts, remaining):
    """Retain held pairs and finish seven distinct, physically feasible pairs.

    Four held copies still supply only one pair. Only existing singletons
    may form the missing pairs; collecting two copies of an absent family
    is omitted from this bounded route set.
    """
    pairs = tuple(i for i, count in enumerate(counts) if count >= 2)
    singles = tuple(i for i, count in enumerate(counts) if count == 1 and remaining[i])
    needed = 7 - len(pairs)
    if needed < 0 or len(singles) < needed:
        return []
    targets = []
    for chosen in combinations(singles, needed):
        families = set(pairs + chosen)
        targets.append(("chiitoi", tuple(2 if i in families else 0 for i in range(34))))
    return targets


def _target_payments(hand, state, remaining, target, deficits):
    """Score completed templates, averaging only physically collectable reds."""
    import advisor as a

    a._check_search()
    held_red = {a.tile_index(tile) for tile in hand if tile.startswith("0")}
    red_pool = {a.tile_index(tile) for tile, _ in a._draw_pool(state, remaining)
                if tile.startswith("0")}
    chances = tuple((index, 1. if index in held_red else
                     deficits[index] / remaining[index] if index in red_pool and remaining[index] else 0.)
                    for index in (4, 13, 22) if target[index])
    seat = state["selfSeat"]
    round_ = state.get("round") or {}
    key = ("target-payments", tuple(target), tuple(i for i, n in enumerate(deficits) if n),
           tuple(sorted(i for i in held_red if target[i])), chances,
           seat, state["playerCount"],
           tuple((meld["type"], tuple(meld["tiles"])) for meld in state["melds"][seat]),
           bool(state.get("replacementWin", False)),
           bool(state.get("riichi", [False] * 4)[seat]),
           bool(state.get("doubleRiichi", [False] * 4)[seat]),
           round_.get("ju", 0), round_.get("chang", 0), round_.get("ben", 0),
           state.get("riichiSticks", 0), state.get("north", [0] * 4)[seat],
           tuple(state.get("doras", [])), tuple(vars(a.OPTIONS).items()))
    cache = a.TABLES.get()
    if cache is not None and key in cache:
        return dict(cache[key])
    variants = [(1., [])]
    for index, chance in chances:
        variants = [(mass * probability, reds + ([index] if red else []))
                    for mass, reds in variants for red, probability in ((False, 1 - chance), (True, chance))
                    if probability]
    payments = {}
    for winning, needed in enumerate(deficits):
        if not needed:
            continue
        expected = 0.
        for mass, reds in variants:
            complete = [a.TILES[i] for i, count in enumerate(target) for _ in range(count)]
            for index in reds:
                complete.remove(a.TILES[index])
                complete.append("0" + a.TILES[index][1])
            tile = a.TILES[winning]
            if tile not in complete:
                tile = "0" + tile[1]
            complete.remove(tile)
            expected += mass * a._hand_value(complete, tile, state, True)["points"]
        payments[winning] = expected
    if cache is not None:
        cache[key] = tuple(payments.items())
    return payments


def _target_outcome(deficits, remaining, events, seat, payments, average,
                    survival, opponent_payments, fees, check):
    """Exact collection urn for one template; all nonwinning draws pay risk."""
    from advisor_policy import Outcome, TABLES

    indices = tuple(i for i, n in enumerate(deficits) if n)
    initial = tuple(deficits[i] for i in indices)
    pool = sum(remaining)
    cache = TABLES.get()
    cache = {} if cache is None else cache
    suffixes = tuple(tuple(events[i:]) for i in range(len(events) + 1))
    risk, loss = average
    live = (1 - risk) * survival

    def outcome(event, draws, needed):
        check()
        # Only unmet families matter. Tile names and the identities of misses
        # cannot affect this fixed-target urn; canonical profiles share tails
        # between root discards, first-draw branches and symmetric honors.
        profile = tuple(sorted((required, remaining[indices[k]] - (initial[k] - required),
                                payments[indices[k]])
                               for k, required in enumerate(needed) if required))
        key = ("target-urn", profile, pool - draws, suffixes[event], seat,
               average, survival, opponent_payments, fees)
        if key in cache:
            return cache[key]
        if event == len(events):
            return (0., 0., 0., 0., 1., fees[int(sum(needed) == 1)])
        if events[event] != seat or draws == pool:
            result = tuple(value * survival for value in outcome(event + 1, draws, needed))
            cache[key] = result
            return result
        win = income = deal = payment = draw = draw_income = useful_mass = 0.
        for k, required in enumerate(needed):
            if not required:
                continue
            copies = remaining[indices[k]] - (initial[k] - required)
            probability = copies / (pool - draws)
            useful_mass += probability
            next_needed = list(needed)
            next_needed[k] -= 1
            if sum(next_needed) == 0:
                win += probability
                income += probability * payments[indices[k]]
            else:
                w, inc, d, paid, exhausted, fee = outcome(event + 1, draws + 1, tuple(next_needed))
                mass = probability * live
                win += mass * w
                income += mass * inc
                deal += probability * risk + mass * d
                payment += probability * loss + mass * paid
                draw += mass * exhausted
                draw_income += mass * fee
        miss = max(0., 1 - useful_mass)
        if miss:
            w, inc, d, paid, exhausted, fee = outcome(event + 1, draws + 1, needed)
            mass = miss * live
            win += mass * w
            income += mass * inc
            deal += miss * risk + mass * d
            payment += miss * loss + mass * paid
            draw += mass * exhausted
            draw_income += mass * fee
        result = win, income, deal, payment, draw, draw_income
        cache[key] = result
        return result

    win, income, deal, loss, draw, draw_income = outcome(0, 0, initial)
    # All residual endings share frozen payments and the same 40/60 split.
    # Recovering them once avoids constructing eleven-field ledger objects
    # in every collection branch; this policy never folds within a target.
    ended = max(0., 1 - win - deal - draw)
    return Outcome(win=win, income=income, deal=deal, loss=loss,
                   tsumo=ended * .4, tsumo_loss=ended * .4 * opponent_payments[0],
                   other=ended * .6, other_loss=ended * .6 * opponent_payments[1],
                   draw=draw, draw_income=draw_income)


def target_policy(hand, state, remaining, opponents, events, discard=None, targets=None, *, average=None, counts=None):
    """Best fixed concrete yaku route, or None if none can reach ready.

    Useful and missed own draws deplete one physical unseen urn without
    replacement. Each nonwinning draw pays a frozen average discard price;
    residual opponent endings use the same public policy hazards. This
    conservative policy claims only tsumo, so untracked miss-discard furiten
    cannot license ron. Other players' unseen draws, later calls, changing
    risk and future riichi are not modeled. Target overlap is never summed.
    """
    import advisor as a

    counts = a.counts34(hand) if counts is None else counts
    seat = state["selfSeat"]
    if targets is None:
        config = a._config(state)
        targets = route_targets(counts, remaining, state["melds"][seat],
                                (31, 32, 33, config.player_wind, config.round_wind))
    survival, opponent_payments, fees = a._policy_environment(state, opponents)
    if average is None:
        _, _, average = a._policy_risks(hand, state, remaining, opponents)
    own_draws = sum(actor == seat for actor in events)
    best = None
    evaluated = []
    seen = set()
    for name, target in targets:
        a._check_search()
        if target in seen:
            continue
        seen.add(target)
        deficits = tuple(max(0, needed - held) for held, needed in zip(counts, target))
        missing = sum(deficits)
        if not missing or missing > own_draws + 1 or any(n > r for n, r in zip(deficits, remaining)):
            continue
        payments = _target_payments(hand, state, remaining, target, deficits)
        if not any(payments.values()):
            continue
        outcome = _target_outcome(deficits, remaining, tuple(events), seat, payments,
                                  average, survival, opponent_payments, fees, a._check_search)
        row = {"route": name, "missingTiles": missing, "target": list(target),
               "winProbability": outcome.win, "winIncome": outcome.income,
               "score": outcome.utility(a._risk_weight(state))}
        evaluated.append(row)
        if best is None or row["score"] > best[0]:
            best = row["score"], outcome, row
    return (best[1] if best else None,
            {"routesEvaluated": len(evaluated), "routes": evaluated,
             "selected": best[2] if best else None,
             "winModes": "tsumo-only", "drawModel": "fixed-target-without-replacement"})
