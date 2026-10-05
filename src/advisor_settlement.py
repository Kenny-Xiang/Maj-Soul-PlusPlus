"""Public opponent-payment estimates for the advisor's terminal ledger.

Ordinary han/fu are the advisor's unfitted estimates, not hidden-hand labels.
Visible yakuman are payment floors: unknown responsibility uses the least
self-payment consistent with the public source metadata. Honba allocation in
any liable/unknown-pao hand is excluded until the rule contract is verified;
hidden yakuman and simultaneous multi-ron settlements are not inferred.
"""
from copy import copy

from mahjong.hand_calculating.scores import ScoresCalculator


def opponent_payments(state, enemy):
    """Return (our payment on enemy tsumo, our payment on other-player ron).

    The other-ron model mixes the non-winning, non-self discarder seats
    uniformly. For the supported public pao components our payment is the
    same for every such seat: half when we are responsible, otherwise zero.
    Existing riichi deposits never form part of our payment.
    """
    seat, winner = state["selfSeat"], enemy["seat"]
    players = state["playerCount"]
    cfg = copy(enemy["config"])
    cfg.kyoutaku_number = 0
    cfg.is_tsumo = True
    own_cost = "main" if seat == state["round"]["ju"] else "additional"
    visible = enemy["yakumanPayment"]
    if not visible:
        closed = not enemy["openMeldCount"]
        prior = 3 if enemy["riichi"] else max(1, enemy["yakuhai"])
        known = (enemy["yakuhai"] + 2 * enemy["allTriplets"] + int(closed) +
                 (2 if cfg.is_daburu_riichi else int(enemy["riichi"])))
        # Four honor groups guarantee honitsu for any suited pair; an honor
        # pair instead gives all-honors yakuman, so two han remain a floor.
        if enemy["meldCount"] == 4 and not any(enemy["visibleCounts"][:27]):
            known += 2
        # The riichi prior already includes unknown yaku; only raise it to
        # the public floor, retaining visible dora/red/North bonuses once.
        han = max(prior, known) + enemy["han"] - prior
        # publicFu contains group/tanki fu and the closed-ron bonus. Tsumo
        # replaces that ten-fu bonus with two fu; the unknown pair adds none.
        public_fu = enemy["publicFu"] - 10 * closed + 2
        fu = max(30, (public_fu + 9) // 10 * 10)
        cost = ScoresCalculator.calculate_scores(han, fu, cfg)
        return cost[own_cost] + cost[own_cost + "_bonus"], 0.

    cfg.tsumi_number = 0
    melds = state["melds"][winner]
    tsumo, other_ron, possible_pao = 0., 0., False
    for name, honors, multiple in (("Daisangen", {"5z", "6z", "7z"}, 1),
                                    ("Daisuushii", {"1z", "2z", "3z", "4z"}, 2),
                                    ("Suukantsu", set(), 1)):
        if name not in visible["yaku"]:
            continue
        responsible = winner  # Winner is the sentinel for no responsibility.
        if honors:
            relevant = [m for m in melds if m["type"] in (1, 2, 3) and m["tiles"][0] in honors]
            last = relevant[-1]
            sources = {s for s in last.get("froms", []) if s in range(players) and s != winner}
            if last["type"] != 3:
                responsible = next(iter(sources)) if len(sources) == 1 else None
        cfg.is_tsumo = True
        cost = ScoresCalculator.calculate_scores(13 * multiple, 0, cfg, True)
        if responsible == winner:
            tsumo += cost[own_cost]
        else:
            possible_pao = True
            if responsible == seat:
                # Sanma retains tsumo loss: only the two existing payments
                # transfer to the responsible feeder, not a phantom fourth.
                tsumo += cost["main"] + (players - 2) * cost["additional"]
                cfg.is_tsumo = False
                ron = ScoresCalculator.calculate_scores(13 * multiple, 0, cfg, True)
                other_ron += ron["main"] / 2
            # Other known feeders pay their component; unknown feeders leave
            # a zero lower bound, not an invented responsibility probability.
    if not possible_pao:
        tsumo += 100 * state["round"].get("ben", 0)
    return tsumo, other_ron
