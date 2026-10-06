"""Nearest physically feasible open-hand targets for explicit yaku routes.

Templates describe complete concealed tiles with existing melds fixed. They
are construction witnesses, not probabilities or guarantees that a draw can
reach them. One nearest target is retained per value honor or toitoi pair;
equal-overlap choices use tile order deterministically, without future data.
"""
from functools import lru_cache
from itertools import combinations, combinations_with_replacement
from math import comb, fsum


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
    held = sum(counts)
    for groups in range(max_groups + 1):
        for pair in (0, 1):
            best = None
            maximum = min(held, 3 * groups + 2 * pair)
            for target, occupied in _patterns(len(counts), groups, pair, suited):
                if any(n > available[i] for i, n in occupied):
                    continue
                retained = sum(min(counts[i], n) for i, n in occupied)
                if best is None or retained > best[0]:
                    best = retained, target
                    if retained == maximum:
                        break
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
        ordered_triplets = sorted((i for i in range(34) if available[i] >= 3),
                                  key=lambda i: (-min(3, counts[i]), i))
        for pair in range(34):
            if available[pair] < 2:
                continue
            triplets = [i for i in ordered_triplets if i != pair]
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


@lru_cache(maxsize=8192)
def _target_occupied(target):
    return tuple((i, n) for i, n in enumerate(target) if n)


@lru_cache(maxsize=8192)
def _target_triplet_win(target):
    # Without any possible sequence this shape has a unique sets/pair
    # decomposition. Self-drawing any triplet leaves every triplet concealed,
    # with identical fu/yaku; the pair's tanki wait must stay separate.
    if target.count(2) != 1 or any(n not in (0, 2, 3) for n in target):
        return None
    if any(target[i] and target[i + 1] and target[i + 2]
           for start in (0, 9, 18) for i in range(start, start + 7)):
        return None
    return next((i for i, n in enumerate(target) if n == 3), None)


def _scoring_context(state):
    import advisor as a

    seat = state["selfSeat"]
    round_ = state.get("round") or {}
    return (seat, state["playerCount"],
           tuple((meld["type"], tuple(meld["tiles"])) for meld in state["melds"][seat]),
           bool(state.get("replacementWin", False)),
           bool(state.get("riichi", [False] * 4)[seat]),
           bool(state.get("doubleRiichi", [False] * 4)[seat]),
           round_.get("ju", 0), round_.get("chang", 0), round_.get("ben", 0),
           state.get("riichiSticks", 0), state.get("north", [0] * 4)[seat],
           tuple(state.get("doras", [])), tuple(vars(a.OPTIONS).items()))


def _target_payment_key(hand, remaining, target, deficits, red_pool, context):
    import advisor as a

    target = tuple(target)
    held_red = {a.tile_index(tile) for tile in hand if tile.startswith("0")}
    chances = tuple((index, 1. if index in held_red else
                     deficits[index] / remaining[index] if index in red_pool and remaining[index] else 0.)
                    for index in (4, 13, 22) if target[index])
    return ("target-payments", target, tuple(i for i, _ in _target_occupied(target) if deficits[i]),
            tuple(sorted(i for i in held_red if target[i])), chances, context)


def _target_payments(hand, state, remaining, target, deficits, *, red_pool=None, key=None):
    """Score completed templates, averaging only physically collectable reds."""
    import advisor as a

    a._check_search()
    if key is None:
        if red_pool is None:
            red_pool = {a.tile_index(tile) for tile, _ in a._draw_pool(state, remaining)
                        if tile.startswith("0")}
        key = _target_payment_key(hand, remaining, target, deficits, red_pool, _scoring_context(state))
    chances = key[4]
    cache = a.TABLES.get()
    if cache is not None and key in cache:
        return dict(cache[key])
    variants = [(1., [])]
    for index, chance in chances:
        variants = [(mass * probability, reds + ([index] if red else []))
                    for mass, reds in variants for red, probability in ((False, 1 - chance), (True, chance))
                    if probability]
    complete_variants = []
    for mass, reds in variants:
        complete = [a.TILES[i] for i, count in enumerate(target) for _ in range(count)]
        for index in reds:
            complete.remove(a.TILES[index])
            complete.append("0" + a.TILES[index][1])
        complete_variants.append((mass, complete))
    payments = {}
    scored = {}
    triplet_win = _target_triplet_win(tuple(target))
    for winning, needed in enumerate(deficits):
        if not needed:
            continue
        score_index = triplet_win if triplet_win is not None and target[winning] == 3 else winning
        if score_index in scored:
            payments[winning] = scored[score_index]
            continue
        expected = 0.
        for mass, template in complete_variants:
            complete = template.copy()
            tile = a.TILES[score_index]
            if tile not in complete:
                tile = "0" + tile[1]
            complete.remove(tile)
            expected += mass * a._hand_value(complete, tile, state, True)["points"]
        payments[winning] = expected
        scored[score_index] = expected
    if cache is not None:
        cache[key] = tuple(payments.items())
    return payments


def _target_convolve(first, second, limit):
    result = [0] * (min(limit, len(first) + len(second) - 2) + 1)
    for i, coefficient in enumerate(first):
        if coefficient:
            for j in range(min(len(second), len(result) - i)):
                if second[j]:
                    result[i + j] += coefficient * second[j]
    return result


def _target_distribution(profile, pool, draws):
    """Exact subset counts, independent of payments and event hazards.

    F_i counts draws meeting family i's quota; replacing F_i by its single
    coefficient at quota - 1 counts paths one tile short in that family.
    Such paths have never completed, so their next useful draw is a first
    completion. All polynomial coefficients stay integers until normalization.
    """
    rest = pool - sum(stock for needed, stock in profile)
    unrelated = [comb(rest, n) for n in range(min(draws, rest) + 1)]
    polynomials = [[0] * min(needed, stock + 1) +
                   [comb(stock, n) for n in range(needed, min(draws, stock) + 1)]
                   for needed, stock in profile]
    prefix = [[1]]
    for polynomial in polynomials:
        prefix.append(_target_convolve(prefix[-1], polynomial, draws))
    suffix = [[1]] * (len(profile) + 1)
    for i in range(len(profile) - 1, -1, -1):
        suffix[i] = _target_convolve(polynomials[i], suffix[i + 1], draws)
    complete = _target_convolve(prefix[-1], unrelated, draws)
    denominators = [comb(pool, n) for n in range(draws + 1)]
    cdf = tuple((complete[n] if n < len(complete) else 0) / denominators[n]
                for n in range(draws + 1))
    singles = {}
    for i, (needed, stock) in enumerate(profile):
        if (needed, stock) in singles:
            continue
        polynomial = _target_convolve(prefix[i], suffix[i + 1], draws)
        polynomial = _target_convolve(polynomial, unrelated, draws)
        scale = comb(stock, needed - 1) if needed - 1 <= stock else 0
        singles[needed, stock] = tuple(
            (polynomial[n - needed + 1] * scale if needed - 1 <= n < len(polynomial) + needed - 1 else 0)
            / denominators[n] for n in range(draws + 1))
    first = tuple(tuple(singles[needed, stock][n - 1] * (stock - needed + 1) / (pool - n + 1)
                        for needed, stock in profile) for n in range(1, draws + 1))
    ready = fsum(singles[family][draws] for family in profile)
    return cdf, first, ready


def _target_outcome(deficits, remaining, events, seat, payments, average,
                    survival, opponent_payments, fees, check):
    """Fixed-target collection distribution, then the unchanged event ledger."""
    from advisor_policy import Outcome, TABLES

    check()
    order = tuple(sorted((i for i, needed in enumerate(deficits) if needed),
                         key=lambda i: (deficits[i], remaining[i])))
    profile = tuple((deficits[i], remaining[i]) for i in order)
    pool = sum(remaining)
    events = tuple(events)
    draws = min(pool, events.count(seat))
    cache = TABLES.get()
    key = ('target-distribution', profile, pool, draws)
    distribution = cache.get(key) if cache is not None else None
    if distribution is None:
        distribution = _target_distribution(profile, pool, draws)
        if cache is not None:
            cache[key] = distribution
    cdf, first, ready = distribution
    risk, loss = average
    live, draw_count = 1., 0
    win = income = deal = payment = 0.
    for actor in events:
        check()
        if actor == seat and draw_count < pool:
            draw_count += 1
            chances = first[draw_count - 1]
            win += live * fsum(chances)
            income += live * fsum(probability * payments[i] for i, probability in zip(order, chances))
            nonwinning = live * (1 - cdf[draw_count])
            deal += nonwinning * risk
            payment += nonwinning * loss
            live *= 1 - risk
        live *= survival
    draw = live * (1 - cdf[-1])
    draw_income = live * ((1 - cdf[-1] - ready) * fees[0] + ready * fees[1])
    ended = max(0., 1 - win - deal - draw)
    return Outcome(win=win, income=income, deal=deal, loss=payment,
                   tsumo=ended * .4, tsumo_loss=ended * .4 * opponent_payments[0],
                   other=ended * .6, other_loss=ended * .6 * opponent_payments[1],
                   draw=draw, draw_income=draw_income)

def target_policy(hand, state, remaining, opponents, events, discard=None, targets=None, *, average=None, counts=None,
                  red_pool=None, context=None):
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
    events = tuple(events)
    pool = sum(remaining)
    cache = a.TABLES.get()
    best = None
    evaluated = []
    seen = set()
    for name, target in targets:
        a._check_search()
        if target in seen:
            continue
        seen.add(target)
        deficits = [0] * 34
        missing, enough = 0, True
        for index, needed in _target_occupied(target):
            if needed > counts[index]:
                deficits[index] = needed - counts[index]
                missing += deficits[index]
                enough = enough and deficits[index] <= remaining[index]
        if not missing or missing > own_draws + 1 or not enough:
            continue
        deficits = tuple(deficits)
        if red_pool is None:
            red_pool = {a.tile_index(tile) for tile, _ in a._draw_pool(state, remaining)
                        if tile.startswith("0")}
        if context is None:
            context = _scoring_context(state)
        payment_key = _target_payment_key(hand, remaining, target, deficits, red_pool, context)
        # Surplus-family identities cannot change a fixed target's payments
        # or urn. Keep the needed families in tile order: no new symmetry or
        # floating-point accumulation order is introduced by this reuse.
        key = ("target-policy", payment_key,
               tuple((deficits[i], remaining[i]) for i in payment_key[2]),
               pool, events, average, survival, opponent_payments, fees)
        if cache is not None and key in cache:
            outcome = cache[key]
        else:
            payments = _target_payments(hand, state, remaining, target, deficits,
                                        red_pool=red_pool, key=payment_key)
            outcome = (_target_outcome(deficits, remaining, events, seat, payments,
                                       average, survival, opponent_payments, fees, a._check_search)
                       if any(payments.values()) else None)
            if cache is not None:
                cache[key] = outcome
        if outcome is None:
            continue
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
