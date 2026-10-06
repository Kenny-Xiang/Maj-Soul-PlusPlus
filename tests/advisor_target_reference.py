"""Frozen event-by-event target urn for differential tests of exact collection."""


def target_outcome(deficits, remaining, events, seat, payments, average,
                    survival, opponent_payments, fees, check):
    """Exact collection urn for one template; all nonwinning draws pay risk."""
    from advisor_policy import Outcome, TABLES

    indices = tuple(i for i, n in enumerate(deficits) if n)
    initial = tuple(deficits[i] for i in indices)
    pool = sum(remaining)
    cache = TABLES.get()
    cache = {} if cache is None else cache
    events = tuple(events)
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
        key = ("target-urn", profile, pool - draws, events[event:], seat,
               average, survival, opponent_payments, fees)
        if key in cache:
            return cache[key]
        if event == len(events):
            return (0., 0., 0., 0., 1., fees[int(sum(needed) == 1)])
        if events[event] != seat or draws == pool:
            next_event = event + 1
            while next_event < len(events) and (events[next_event] != seat or draws == pool):
                check()
                next_event += 1
            result = outcome(next_event, draws, needed)
            # Preserve one multiplication per original event, including its
            # rounding, while avoiding identical urn profiles between draws.
            for _ in range(next_event - event):
                result = tuple(value * survival for value in result)
            cache[key] = result
            return result
        win = income = deal = payment = draw = draw_income = useful_mass = 0.
        last_needed = sum(needed) == 1
        for k, required in enumerate(needed):
            if not required:
                continue
            copies = remaining[indices[k]] - (initial[k] - required)
            probability = copies / (pool - draws)
            useful_mass += probability
            next_needed = list(needed)
            next_needed[k] -= 1
            if last_needed:
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



def local_choices(counts, available, max_groups, suited):
    from advisor_routes import _patterns

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



def route_targets(counts, remaining, melds, value_honors):
    """Return concrete toitoi and value-honor targets, with existing melds fixed.

    Missing tiles must exist in the public unseen pool. The nearest target
    maximizes tiles retained from the current concealed hand; its shanten is
    sum(target) - 1 - sum(min(held, needed)). No yaku prior is involved.
    """
    from advisor_routes import _index, _regular_target

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

