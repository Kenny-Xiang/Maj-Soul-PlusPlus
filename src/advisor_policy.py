"""Small frozen-public-state policies, with one mutually exclusive ledger.

This is a bounded policy comparison, not hidden-hand search. A fold forgoes
wins. Safe new draws preserve held stock and existing tenpai; safe-draw mass
is depleted without replacement. Spending held stock forfeits tenpai fees.
Other draw identities and later opponent changes stay frozen.
"""
from typing import NamedTuple
from contextvars import ContextVar


TABLES = ContextVar("advisor_policy_tables", default=None)


class Outcome(NamedTuple):
    win: float = 0.
    income: float = 0.
    deal: float = 0.
    loss: float = 0.
    tsumo: float = 0.
    tsumo_loss: float = 0.
    other: float = 0.
    other_loss: float = 0.
    draw: float = 0.
    draw_income: float = 0.
    fold: float = 0.
    rank_adjustment: float = 0.

    def scale(self, mass):
        return Outcome(*(x * mass for x in self))

    def __add__(self, other):
        return Outcome(*(x + y for x, y in zip(self, other)))

    def utility(self, risk_weight):
        return (self.income - risk_weight * self.loss - self.tsumo_loss - self.other_loss +
                self.draw_income + self.rank_adjustment)

    def metrics(self):
        return self.win, self.income / self.win if self.win else 0., self.deal, self.loss


def residual(next_, survival, tsumo_payment, other_payment):
    """Partition the old residual hazard once, after our explicit outcomes."""
    return advance(next_, 0., 0., survival, (tsumo_payment, other_payment))


def discard(next_, risk, loss, *, rank_adjustment=0.):
    return advance(next_, risk, loss, 1., (0., 0.), rank_adjustment=rank_adjustment)


def advance(next_, risk, loss, survival, payments, win=0., income=0., *, rank_adjustment=0.):
    """Discard and residual ending, composed without intermediate ledgers."""
    live = (1 - risk - win) * survival
    end = (1 - risk - win) * (1 - survival)
    return Outcome(win + next_.win * live, income + next_.income * live,
                   risk + next_.deal * live, loss + next_.loss * live,
                   next_.tsumo * live + end * .4,
                   next_.tsumo_loss * live + end * .4 * payments[0],
                   next_.other * live + end * .6,
                   next_.other_loss * live + end * .6 * payments[1],
                   next_.draw * live, next_.draw_income * live, next_.fold * live,
                   rank_adjustment + next_.rank_adjustment * live)


def fold_table(events, seat, stock, average, survival, payments, noten_fee, check, *,
               safe_draws=None, tenpai_fee=None, deplete_prefix=False):
    """One fold outcome per suffix, consuming original stock from its start.

    Enemy-only gaps have constant residual hazards and can be summed once;
    only our draws consume stock or cause a discard payment. Each suffix
    starts with the original stock. Columns condition on the first draw.
    """
    stock = tuple((*price, 0.) if len(price) == 2 else price for price in stock)
    average = (*average, 0.) if len(average) == 2 else average
    cache = TABLES.get()
    key = ("fold", tuple(events), seat, tuple(stock), average, survival, payments,
           noten_fee, safe_draws, tenpai_fee, deplete_prefix)
    if cache is not None and key in cache:
        check()
        return cache[key]
    if safe_draws and safe_draws[0]:
        table = _safe_draw_fold_table(events, seat, stock, average, survival, payments,
                                      noten_fee, check, safe_draws, tenpai_fee, deplete_prefix)
        if cache is not None:
            cache[key] = table
        return table
    own = [i for i, actor in enumerate(events) if actor == seat]
    powers, endings = [1.], [0.]
    for _ in events:
        # Sum the geometric hazard rather than subtracting 1 - survival**n:
        # the latter loses precision when survival is close to one.
        endings.append(endings[-1] + powers[-1] * (1 - survival))
        powers.append(powers[-1] * survival)
    table, cursor = [], 0
    for start in range(len(events) + 1):
        check()
        while cursor < len(own) and own[cursor] < start:
            cursor += 1
        live, deal, loss, ended, adjustment = 1., 0., 0., 0., 0.
        previous = start
        for k, index in enumerate(own[cursor:]):
            gap = index - previous
            ended += live * endings[gap]
            live *= powers[gap]
            risk, payment, preference = stock[k] if k < len(stock) else average
            deal += live * risk
            loss += live * payment
            adjustment += live * preference
            live *= 1 - risk
            ended += live * (1 - survival)
            live *= survival
            previous = index + 1
        ended += live * endings[len(events) - previous]
        live *= powers[len(events) - previous]
        fee = tenpai_fee if tenpai_fee is not None and cursor == len(own) else noten_fee
        outcome = Outcome(deal=deal, loss=loss, tsumo=ended * .4,
                          tsumo_loss=ended * .4 * payments[0], other=ended * .6,
                          other_loss=ended * .6 * payments[1], draw=live,
                          draw_income=live * fee, rank_adjustment=adjustment)
        table.append([outcome, outcome, outcome])
    if cache is not None:
        cache[key] = table
    return table


def _safe_draw_fold_table(events, seat, stock, average, survival, payments, noten_fee, check,
                          safe_draws, tenpai_fee, deplete_prefix):
    """Track safe physical draws and original stock, never unknown safe rivers.

    Each row contains unknown, known-unsafe and known-safe first-draw policies.
    The latter two prevent a post-draw decision from redrawing that same tile.
    Only the safe/unsafe class is sampled without replacement; after original
    stock is spent, the conditional unsafe draw price stays frozen.
    Suffix entry after unspecified prior misses conservatively depletes one
    safe tile per prior draw, avoiding reuse of already discarded safe tiles.
    """
    safe, pool = safe_draws
    unsafe_average = tuple(x * pool / (pool - safe) for x in average) if pool > safe else (0., 0., 0.)
    table = []
    prior_draws = 0
    for start in range(len(events) + 1):
        check()
        if start and events[start - 1] == seat:
            prior_draws += 1
        prefix = prior_draws if deplete_prefix else 0
        safe_left, pool_left = max(0, safe - prefix), max(0, pool - prefix)
        row = []
        for conditioned in (None, False, True):
            live = {0: 1.}
            draws = 0
            deal = loss = ended = adjustment = 0.
            for actor in events[start:]:
                check()
                if actor == seat:
                    nxt = {}
                    for used, mass in live.items():
                        probability = (max(0., min(1., (safe_left - (draws - used)) / (pool_left - draws)))
                                       if pool_left > draws else 0.)
                        if conditioned is not None and not draws:
                            probability = float(conditioned)
                        risk, payment, preference = stock[used] if used < len(stock) else unsafe_average
                        safe_mass, unsafe_mass = mass * probability, mass * (1 - probability)
                        if safe_mass:
                            nxt[used] = nxt.get(used, 0.) + safe_mass
                        if unsafe_mass:
                            deal += unsafe_mass * risk
                            loss += unsafe_mass * payment
                            adjustment += unsafe_mass * preference
                            nxt[used + 1] = nxt.get(used + 1, 0.) + unsafe_mass * (1 - risk)
                    live = nxt
                    draws += 1
                ended += sum(live.values()) * (1 - survival)
                live = {used: mass * survival for used, mass in live.items()}
            draw = sum(live.values())
            draw_income = draw * noten_fee
            if tenpai_fee is not None:
                draw_income += live.get(0, 0.) * (tenpai_fee - noten_fee)
            row.append(Outcome(deal=deal, loss=loss, tsumo=ended * .4,
                               tsumo_loss=ended * .4 * payments[0], other=ended * .6,
                               other_loss=ended * .6 * payments[1], draw=draw,
                               draw_income=draw_income, rank_adjustment=adjustment))
        table.append(row)
    return table


def ready_table(events, seat, ron, draws, stock, average, survival, payments,
                fees, risk_weight, locked, check, *, defense_stock=None, safe_draws=None):
    """Compare continue and commit-to-fold after each non-winning draw.

    Draw tuples are (physical weight / pool, tsumo points, risk, loss,
    signed rank preference); legacy tuples default to zero preference.
    Each policy's income, risk and draw fee travel together through the tree.
    """
    draws = tuple((*draw, 0.) if len(draw) == 4 else draw for draw in draws)
    cache = TABLES.get()
    key = ("ready", tuple(events), seat, ron, tuple(draws), tuple(stock), average,
           survival, payments, fees, risk_weight, locked,
           tuple(defense_stock) if defense_stock is not None else None, safe_draws)
    if cache is not None and key in cache:
        check()
        return cache[key]
    folded = None if locked else fold_table(events, seat, stock if defense_stock is None else defense_stock,
                                            average, survival, payments, fees[0], check,
                                            safe_draws=safe_draws, deplete_prefix=True)
    table = [None] * (len(events) + 1)
    table[-1] = Outcome(draw=1., draw_income=fees[1])
    for i in range(len(events) - 1, -1, -1):
        check()
        if events[i] != seat:
            hit, income = ron
            table[i] = advance(table[i + 1], 0., 0., survival, payments, hit, income)
            continue
        nxt = residual(table[i + 1], survival, *payments)
        fold = None
        if folded is not None and stock:
            # This decision follows a known unsafe draw; do not average over
            # a second, hypothetical safe draw before spending held stock.
            fold = folded[i][1]._replace(fold=1.)
        win = income = deal = loss_total = continuing = folding = adjustment = 0.
        next_utility = nxt.utility(risk_weight)
        fold_utility = fold.utility(risk_weight) if fold is not None else float("-inf")
        for mass, points, risk, loss, preference in draws:
            if points:
                win += mass
                income += mass * points
            elif risk and fold_utility > (1 - risk) * next_utility - risk_weight * loss + preference:
                folding += mass
            else:
                continuing += mass * (1 - risk)
                deal += mass * risk
                loss_total += mass * loss
                adjustment += mass * preference
        f = fold if folding else Outcome()
        table[i] = Outcome(win + nxt.win * continuing + f.win * folding,
                           income + nxt.income * continuing + f.income * folding,
                           deal + nxt.deal * continuing + f.deal * folding,
                           loss_total + nxt.loss * continuing + f.loss * folding,
                           nxt.tsumo * continuing + f.tsumo * folding,
                           nxt.tsumo_loss * continuing + f.tsumo_loss * folding,
                           nxt.other * continuing + f.other * folding,
                           nxt.other_loss * continuing + f.other_loss * folding,
                           nxt.draw * continuing + f.draw * folding,
                           nxt.draw_income * continuing + f.draw_income * folding,
                           nxt.fold * continuing + f.fold * folding,
                           adjustment + nxt.rank_adjustment * continuing + f.rank_adjustment * folding)
    if cache is not None:
        cache[key] = table
    return table
