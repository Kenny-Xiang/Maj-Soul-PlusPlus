"""One common physical draw/discard frontier, then explicit approximate tails.

All non-ready root candidates use the same depth, including shape changes
which preserve shanten. The unseen pool is not the live wall. No future call
or riichi is assumed. Only the first draw is sampled without replacement;
continuation hazards are frozen public-information estimates.
"""
from copy import deepcopy
from advisor_routes import _scoring_context, route_targets, seven_pair_targets, target_policy


def leaf_policy(hand, state, remaining, opponents, events, discard=None, *, shape=None):
    """A common coarse leaf, with physical targets for dominant seven pairs."""
    import advisor as a

    special = not state['melds'][state['selfSeat']]
    if shape is None:
        counts = a.counts34(hand)
        sh = a.shanten(counts, special)
    else:
        counts, sh, ukeire = shape
    chiitoi = (special and sh <= 2 and
               a.Shanten.calculate_shanten_for_chiitoitsu_hand(counts) == sh and
               a.shanten(counts, False) > sh)
    # Ordinary progress cannot borrow the wider special-hand ukeire or its
    # two-han value while skipping the seventh distinct pair prerequisite.
    shape_special = special and not chiitoi
    if chiitoi:
        sh = a.shanten(counts, False)
    if chiitoi or shape is None:
        ukeire = sum(t['count'] for t in a._improvements(counts, remaining, shape_special))
    value, factor = a._future_value(hand, state, counts, shape_special, tsumo=True)
    ron = a._future_value(hand, state, counts, shape_special)
    _, _, average = a._policy_risks((), state, remaining, opponents)
    survival, payments, fees = a._policy_environment(state, opponents)
    cache = a.TABLES.get()
    cache = {} if cache is None else cache
    key = ('finite-tail', tuple(events), sh, ukeire, value, factor, ron,
           sum(remaining), average, survival, payments, fees)
    if key not in cache:
        cache[key] = a._coarse_policy(hand, state, remaining, opponents,
                                     events, sh, ukeire, value, factor, ron=ron)
    outcome = cache[key]
    if chiitoi:
        pair_outcome, _ = target_policy(hand, state, remaining, opponents, events, discard,
                                        seven_pair_targets(counts, remaining), average=average)
        if pair_outcome is not None and pair_outcome.utility(a._risk_weight(state)) > outcome.utility(a._risk_weight(state)):
            outcome = pair_outcome
    return outcome



def finite_policy(hand, state, remaining, opponents, events, discard=None):
    import advisor as a

    seat = state['selfSeat']
    special = not state['melds'][seat]
    counts = a.counts34(hand)
    current = a.shanten(counts, special)
    survival, payments, fees = a._policy_environment(state, opponents)
    detail = {'ownDrawDepth': 1, 'drawVariants': 0, 'discardVariants': 0,
              'sameShantenChangeMass': 0., 'expectedNextUkeire': 0.,
              'unchangedNextUkeire': 0., 'yakuRoutes': None,
              'tail': 'projected-progress-without-future-calls-or-riichi'}
    if seat not in events or not sum(remaining):
        result = a.Outcome(draw=1., draw_income=fees[0])
        for _ in events:
            result = a._policy_residual(result, survival, *payments)
        return result, detail
    first = events.index(seat)
    suffix = events[first + 1:]
    after = deepcopy(state)
    after['hand'] = hand.copy()
    if discard is not None:
        after['rivers'][seat].append({'tile': discard})
    # The root discard has passed only in this continuation.
    root_pool = sum(remaining)
    cfg = a._config(state)
    targets = []
    if (any(m['type'] != 3 for m in state['melds'][seat]) and
            not a._future_value(hand, state, counts, special, tsumo=True)[1]):
        targets = route_targets(counts, remaining, state['melds'][seat],
                                (31, 32, 33, cfg.player_wind, cfg.round_wind))
    _, _, target_average = a._policy_risks((), state, remaining, opponents)
    witnesses = []
    result = a.Outcome()
    weight = a._risk_weight(state)
    context = _scoring_context(state)
    cache = a.TABLES.get()
    cache = {} if cache is None else cache
    continuation_context = (context, tuple(suffix), survival, payments, fees, weight,
                            bool(state.get('furiten', False)))
    own_river = frozenset(a.tile_index(d['tile']) for d in after['rivers'][seat])
    pool = sorted(a._draw_pool(after, remaining))
    initial_red = frozenset(a.tile_index(tile) for tile, _ in pool if tile.startswith('0'))
    for draw, mass in pool:
        a._check_search()
        index = a.tile_index(draw)
        unseen = list(remaining)
        unseen[index] -= 1
        unseen = tuple(unseen)
        red_pool = initial_red - {index} if draw.startswith('0') or not unseen[index] else initial_red
        drawn = {**after, 'hand': [*hand, draw], 'lastDraw': draw,
                 'forbiddenDiscards': []}
        current_opponents = opponents
        best = None
        selected_route = None
        priced_discards = {}
        discard_states = {}
        unchanged = sum(t['count'] for t in a._improvements(counts, unseen, special))
        detail['unchangedNextUkeire'] += mass / root_pool * unchanged
        # A non-ready hand cannot self-draw on this first draw. Future choices
        # include every physical discard; red and ordinary fives stay distinct.
        for tile in sorted(set(drawn['hand'])):
            a._check_search()
            nxt_hand = a._remove_exact(drawn['hand'], [tile])
            danger, loss, _ = a._danger(tile, unseen, current_opponents)
            priced_discards[tile] = (danger, loss)
            future = [{**o, 'safe': o['safe'] | {a.tile_index(tile)} if o['riichi'] else o['safe']}
                      for o in opponents]
            # Root A then B and root B then A can reach exactly the same
            # future hand. Keep both passed discards for furiten and safety.
            key = ('finite-continuation', continuation_context, tuple(sorted(nxt_hand)), unseen,
                   own_river | {a.tile_index(tile)}, red_pool,
                   tuple((o['seat'], o['riichi'], frozenset(o['safe']), o['tenpai']) for o in future))
            if key in cache:
                nxt_counts, sh, ukeire, continuation = cache[key]
            else:
                nxt_counts = a.counts34(nxt_hand)
                sh = a.shanten(nxt_counts, special)
                ukeire = sum(t['count'] for t in a._improvements(nxt_counts, unseen, special))
                if sh == 0:
                    waits, _ = a._wait_values(nxt_hand, nxt_counts, unseen, drawn, tile, special)
                    continuation = a._ready_policy(nxt_hand, drawn, unseen, future, suffix, waits)[0]
                elif special and sh <= 2 and a.Shanten.calculate_shanten_for_kokushi_hand(nxt_counts) == sh:
                    ron_value = a._future_value(nxt_hand, drawn, nxt_counts, special)[0]
                    tsumo_value = a._future_value(nxt_hand, drawn, nxt_counts, special, tsumo=True)[0]
                    continuation = a._kokushi_outcome(nxt_counts, unseen, future, drawn, tile,
                                                       suffix, ron_value, tsumo_value=tsumo_value)
                else:
                    # Every distance has the same leaf contract. Unknown open yaku
                    # never acquires the old .3 income simply by moving backwards.
                    continuation = leaf_policy(nxt_hand, drawn, unseen, future, suffix, tile,
                                               shape=(nxt_counts, sh, ukeire))
                continuation = a._policy_residual(continuation, survival, *payments)
                cache[key] = nxt_counts, sh, ukeire, continuation
            discard_states[tile] = nxt_hand, nxt_counts, sh, ukeire
            outcome = a._policy_discard(continuation, danger, loss)
            preference = (outcome.utility(weight), -a._adverse_payments(outcome), -loss,
                          -sh, ukeire, tile)
            if best is None or preference > best[0]:
                best = preference, outcome, tile, sh, ukeire
            detail['discardVariants'] += 1
        # A target is chosen after seeing this draw, so retaining two value
        # honors preserves both branches without summing overlapping wins.
        drawn_counts = a.counts34(drawn['hand'])
        held_red = tuple(t for t in drawn['hand'] if t.startswith('0'))
        for name, target in targets:
            a._check_search()
            surplus = [t for t in priced_discards if drawn_counts[a.tile_index(t)] > target[a.tile_index(t)]]
            # Retained red identity determines the common target tail. Keep
            # each discard's current risk until comparing its full utility.
            choices = {}
            for tile in surplus:
                retained_red = tuple(t for t in held_red if t != tile
                                     and target[a.tile_index(t)])
                key = tuple(sorted(retained_red))
                choices.setdefault(key, []).append(tile)
            for equivalent in choices.values():
                tile = equivalent[0]
                nxt_hand, nxt_counts, sh, ukeire = discard_states[tile]
                continuation, metadata = target_policy(nxt_hand, drawn, unseen, opponents, suffix,
                                                       tile, [(name, target)], average=target_average, counts=nxt_counts,
                                                       red_pool=red_pool, context=context)
                if continuation is None:
                    continue
                continuation = a._policy_residual(continuation, survival, *payments)
                for tile in equivalent:
                    _, _, sh, ukeire = discard_states[tile]
                    danger, loss = priced_discards[tile]
                    outcome = a._policy_discard(continuation, danger, loss)
                    preference = (outcome.utility(weight), -a._adverse_payments(outcome), -loss,
                                  -sh, ukeire, tile)
                    if best is None or preference > best[0]:
                        best = preference, outcome, tile, sh, ukeire
                        selected_route = {'draw': draw, 'drawMass': mass / root_pool, 'discard': tile,
                                          **metadata['selected']}
        if selected_route is not None:
            witnesses.append(selected_route)
        detail['drawVariants'] += 1
        _, outcome, tile, sh, ukeire = best
        result += outcome.scale(mass / root_pool)
        detail['expectedNextUkeire'] += mass / root_pool * ukeire
        if sh == current and a.tile_index(tile) != index:
            detail['sameShantenChangeMass'] += mass / root_pool
    detail['yakuRoutes'] = {'chosen': bool(witnesses), 'drawContingent': True,
                            'routesEvaluated': len(targets), 'routes': witnesses,
                            'selected': max(witnesses, key=lambda r: r['drawMass']) if witnesses else None,
                            'winModes': 'tsumo-only', 'drawModel': 'fixed-target-without-replacement'}
    for _ in events[:first]:
        result = a._policy_residual(result, survival, *payments)
    return result, detail
