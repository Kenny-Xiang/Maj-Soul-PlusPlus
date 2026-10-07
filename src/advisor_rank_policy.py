"""Bounded rank-point preferences, not an estimated final-placement EV.

Smooth the official placement rewards over score gaps, then compare symmetric
4000-point transfers. Actual predicted discard payments then retain the
receiving opponent's score. The smoothing width, transfer size and weight
bounds are unfitted policy choices. Match-ending probability, dealer
continuation and future score distributions are not inferred by this proxy.
"""
from functools import lru_cache
from math import exp, fsum, isfinite, sqrt

from advisor_rank import profile_for_match


MATCH_FIELDS = ('source', 'category', 'modeId', 'room', 'levelId', 'playerCount', 'roundCount')
PROBE_POINTS = 4000
BASE_WEIGHT = 1.15


def _potential(scores, seat, rewards, divisor, scale):
    """Interpolate placement rewards; these weights are not win probabilities."""
    distribution = [1.]
    for other, score in enumerate(scores):
        if other == seat:
            continue
        gap = max(-60., min(60., (scores[seat] - score) / scale))
        ahead = 1 / (1 + exp(gap))
        next_ = [0.] * (len(distribution) + 1)
        for place, mass in enumerate(distribution):
            next_[place] += mass * (1 - ahead)
            next_[place + 1] += mass * ahead
        distribution = next_
    return (scores[seat] / divisor if divisor else 0.) + fsum(
        mass * reward for mass, reward in zip(distribution, rewards))


@lru_cache(maxsize=256)
def _context(match_values, levels, scores, seat, chang, ju):
    match = dict(zip(MATCH_FIELDS, match_values), levelIds=list(levels))
    players = len(scores)
    profile = profile_for_match(match, players)
    if profile is None:
        return None
    remaining = max(0, players * profile['roundCount'] - (chang * players + ju) - 1)
    scale = PROBE_POINTS * sqrt(remaining + 1)
    rewards, divisor = profile['placementPoints'], profile['scoreDivisor']
    baseline = _potential(scores, seat, rewards, divisor, scale)
    gains, losses = [], []
    for rival in range(players):
        if rival == seat:
            continue
        up, down = list(scores), list(scores)
        up[seat] += PROBE_POINTS
        up[rival] -= PROBE_POINTS
        down[seat] -= PROBE_POINTS
        down[rival] += PROBE_POINTS
        gains.append(_potential(up, seat, rewards, divisor, scale) - baseline)
        losses.append(baseline - _potential(down, seat, rewards, divisor, scale))
    gain, loss = fsum(gains) / (players - 1), fsum(losses) / (players - 1)
    # Pure placement rewards can saturate when every gap is overwhelming.
    # Do not amplify floating-point cancellation into an extreme preference.
    raw = BASE_WEIGHT * loss / gain if min(gain, loss) > 1e-10 else BASE_WEIGHT
    weight = max(.75, min(1.75, raw))
    own = scores[seat]
    above, tied = sum(s > own for s in scores), sum(s == own for s in scores)
    return {'active': True, 'source': 'auth-game', 'objective': 'rank-points',
            'method': 'bounded-rank-potential', 'lossMethod': 'bounded-rank-transfer', 'profile': profile,
            'rankRange': [above + 1, above + tied], 'dealer': ju == seat,
            'gapToFirst': max(scores) - own, 'gapAboveLast': own - min(scores),
            'remainingScheduledHands': remaining, 'smoothingPoints': scale,
            'probePoints': PROBE_POINTS, 'probeGain': gain, 'probeLoss': loss,
            'rawRiskWeight': raw, 'riskWeight': weight,
            'riskWeightAdjustment': weight - BASE_WEIGHT,
            'preference': 'protect' if weight > BASE_WEIGHT else 'push' if weight < BASE_WEIGHT else 'balanced'}


def ranked_context(state):
    """Require verified match metadata and complete scores; otherwise fall back."""
    match, round_ = state.get('match'), state.get('round')
    players, seat = state.get('playerCount'), state.get('selfSeat')
    if not isinstance(match, dict) or not isinstance(round_, dict):
        return None
    if type(players) is not int or players not in (3, 4) or type(seat) is not int or not 0 <= seat < players:
        return None
    scores = state.get('scores', [])[:players]
    if len(scores) != players or any(type(s) not in (int, float) or not isfinite(s) for s in scores):
        return None
    chang, ju = round_.get('chang'), round_.get('ju')
    if type(chang) is not int or chang < 0 or type(ju) is not int or not 0 <= ju < players:
        return None
    values = tuple(match.get(key) for key in MATCH_FIELDS)
    if not isinstance(values[0], str) or any(type(value) is not int for value in values[1:]):
        return None
    levels = match.get('levelIds', [])
    if not isinstance(levels, (list, tuple)) or any(level is not None and type(level) is not int for level in levels):
        return None
    return _context(values, tuple(levels), tuple(scores), seat, chang, ju)


def loss_context(state):
    """Immutable pricing inputs, also distinguishing hypothetical riichi costs."""
    context = ranked_context(state)
    if context is None:
        return None
    profile = context['profile']
    return (tuple(state['scores'][:state['playerCount']]), state['selfSeat'],
            tuple(profile['placementPoints']), profile['scoreDivisor'],
            context['smoothingPoints'], context['probeGain'], context['riskWeight'])


@lru_cache(maxsize=4096)
def loss_adjustment(context, rival, payment):
    """Signed point-scale preference, separate from the predicted cash payment.

    Normalize the actual score transfer by the existing average gain probe.
    This remains a bounded preference, not final-placement expected value.
    """
    if context is None or payment <= 0:
        return 0.
    scores, seat, rewards, divisor, scale, gain, old_weight = context
    if gain <= 1e-10:
        return 0.
    after = list(scores)
    after[seat] -= payment
    after[rival] += payment
    loss = (_potential(scores, seat, rewards, divisor, scale) -
            _potential(after, seat, rewards, divisor, scale))
    weight = max(.75, min(1.75, BASE_WEIGHT * loss / gain * PROBE_POINTS / payment))
    return (old_weight - weight) * payment
