"""Streaming action diagnostics for recorded choices, not estimates of playing strength."""
from collections import Counter
from copy import deepcopy
import math

import numpy as np

from policy_features import ACTIONS, ACTION_NAMES, TILES37, tile34


_COUNTS = ("opportunityCount", "actualPositive", "predictedPositive", "truePositive",
           "falsePositive", "falseNegative", "trueNegative", "exactCorrectPositive",
           "exactFalsePositive", "exactFalseNegative", "exactCorrect",
           "typeCorrectParameterMismatch")
_MISMATCHES = ("tile", "baseTile", "redIdentityOnly", "moqie", "otherParameters")
_MARGINS = ("allPairs", "windowMeans", "recordedRiichiPair", "recordedDiscardPair")
_SCORES = ("recordedCandidateNll", "recordedTypeNll", "recordedCandidateMargin",
           "bestTypeVsOtherMargin", "logitRange", "tiedMaximum")


def _moments():
    return {"count": 0, "sum": 0., "sumSquares": 0., "minimum": None,
            "maximum": None, "positive": 0, "negative": 0, "zero": 0}


def _add_moment(item, value):
    item["count"] += 1
    item["sum"] += value
    item["sumSquares"] += value * value
    item["minimum"] = value if item["minimum"] is None else min(item["minimum"], value)
    item["maximum"] = value if item["maximum"] is None else max(item["maximum"], value)
    item["positive" if value > 0 else "negative" if value < 0 else "zero"] += 1


def _merge_moments(item, source):
    if not source["count"]:
        return
    for key in ("minimum", "maximum"):
        combine = min if key == "minimum" else max
        item[key] = source[key] if item[key] is None else combine(item[key], source[key])
    for key in ("count", "sum", "sumSquares", "positive", "negative", "zero"):
        item[key] += source[key]


def _finish_moments(item):
    result = deepcopy(item)
    result["mean"] = item["sum"] / item["count"] if item["count"] else None
    result["standardDeviation"] = (math.sqrt(max(0., item["sumSquares"] / item["count"] - result["mean"] ** 2))
                                   if item["count"] else None)
    return result


def _tile(vector):
    values = vector[len(ACTIONS):len(ACTIONS) + len(TILES37)]
    return TILES37[int(np.argmax(values))] if np.any(values) else None


def _parameter_mismatches(actual, predicted):
    first, second = _tile(actual), _tile(predicted)
    same_base = ((tile34(first) if first is not None else None) ==
                 (tile34(second) if second is not None else None))
    return {"tile": first != second, "baseTile": not same_base,
            "redIdentityOnly": same_base and first != second,
            "moqie": not np.array_equal(actual[-3:], predicted[-3:]),
            "otherParameters": not np.array_equal(
                actual[len(ACTIONS) + len(TILES37):-3],
                predicted[len(ACTIONS) + len(TILES37):-3])}


class ActionDiagnostics:
    """Consume encoded samples and raw logits; keep only mergeable aggregates.

    Predictions use the first maximum in candidate order, matching deployed NumPy
    inference. Padded logit columns are ignored. Forced windows are counted but
    excluded from opportunity metrics, as in the existing corpus evaluator.
    """

    def __init__(self, action_types=("riichi", "daiminkan")):
        self.action_types = tuple(action_types)
        if not self.action_types or len(set(self.action_types)) != len(self.action_types):
            raise ValueError("diagnostic action types must be nonempty and unique")
        if any(action not in ACTIONS for action in self.action_types):
            raise ValueError("unknown diagnostic action type")
        self.samples = self.choices = self.forced = 0
        self.items = {action: {"counts": Counter(dict.fromkeys(_COUNTS, 0)),
                               "typeConfusion": Counter(),
                               "parameterMismatches": Counter(dict.fromkeys(_MISMATCHES, 0)),
                               "parameterMismatchPatterns": Counter()}
                      for action in self.action_types}
        self.margins = {name: _moments() for name in _MARGINS}
        self.scores = {action: {stratum: {name: _moments() for name in _SCORES}
                                for stratum in ("actualPositive", "actualNegative")}
                       for action in self.action_types}

    def update(self, sample, logits):
        actions = np.asarray(sample["actions"])
        scores = np.asarray(logits)
        target = sample["target"]
        if (actions.ndim != 2 or actions.shape[1] != len(ACTION_NAMES) or
                not len(actions) or scores.ndim != 1 or len(scores) < len(actions) or
                not isinstance(target, (int, np.integer)) or not 0 <= target < len(actions)):
            raise ValueError("invalid diagnostic actions, logits, or target dimensions")
        scores = scores[:len(actions)]
        if not np.isfinite(scores).all():
            raise ValueError("nonfinite legal-candidate logits")
        types = np.argmax(actions[:, :len(ACTIONS)], axis=1)
        actual = ACTIONS[types[target]]
        if sample.get("action", actual) != actual:
            raise ValueError("recorded action type disagrees with encoded target")
        self.samples += 1
        if len(actions) == 1:
            self.forced += 1
            return
        self.choices += 1
        best = int(np.argmax(scores))
        predicted = ACTIONS[types[best]]
        correct = best == target
        for action, item in self.items.items():
            if ACTIONS.index(action) not in types:
                continue
            positive, selected = actual == action, predicted == action
            item["counts"].update({
                "opportunityCount": 1, "actualPositive": int(positive),
                "predictedPositive": int(selected), "truePositive": int(positive and selected),
                "falsePositive": int(not positive and selected),
                "falseNegative": int(positive and not selected),
                "trueNegative": int(not positive and not selected),
                "exactCorrectPositive": int(positive and correct),
                "exactFalsePositive": int(selected and not correct),
                "exactFalseNegative": int(positive and not correct),
                "exactCorrect": int(correct),
                "typeCorrectParameterMismatch": int(positive and selected and not correct)})
            item["typeConfusion"][(actual, predicted)] += 1
            self._update_scores(action, scores, types, target, positive)
            if positive and selected and not correct:
                differences = _parameter_mismatches(actions[target], actions[best])
                item["parameterMismatches"].update({key: int(value) for key, value in differences.items()})
                pattern = "+".join(key for key, value in differences.items() if value and key != "tile")
                item["parameterMismatchPatterns"][pattern] += 1
        if "riichi" in self.items and ACTIONS.index("riichi") in types:
            self._update_margins(actions, scores, types, target)

    def _update_scores(self, action, scores, types, target, positive):
        # Center first: adding log(Z) to a huge shared score can lose the NLL.
        centered = scores.astype(np.float64) - float(np.max(scores))
        log_z = math.log(float(np.exp(centered).sum()))
        actual_type = centered[types == types[target]]
        type_max = float(np.max(actual_type))
        type_log_z = type_max + math.log(float(np.exp(actual_type - type_max).sum()))
        values = {"recordedCandidateNll": log_z - float(centered[target]),
                  "recordedTypeNll": log_z - type_log_z,
                  "recordedCandidateMargin": float(centered[target]) - float(np.max(np.delete(centered, target))),
                  "logitRange": -float(np.min(centered)),
                  "tiedMaximum": float(np.count_nonzero(centered == 0) > 1)}
        focal = types == ACTIONS.index(action)
        if np.any(~focal):
            values["bestTypeVsOtherMargin"] = float(np.max(centered[focal]) - np.max(centered[~focal]))
        item = self.scores[action]["actualPositive" if positive else "actualNegative"]
        for name, value in values.items():
            _add_moment(item[name], value)

    def _update_margins(self, actions, scores, types, target):
        discards = {row[len(ACTIONS):].tobytes(): index for index, row in enumerate(actions)
                    if ACTIONS[types[index]] == "discard"}
        margins = []
        for index, row in enumerate(actions):
            if ACTIONS[types[index]] != "riichi":
                continue
            other = discards.get(row[len(ACTIONS):].tobytes())
            if other is None:
                continue
            margin = float(scores[index]) - float(scores[other])
            margins.append(margin)
            _add_moment(self.margins["allPairs"], margin)
            if index == target:
                _add_moment(self.margins["recordedRiichiPair"], margin)
            if other == target:
                _add_moment(self.margins["recordedDiscardPair"], margin)
        if margins:
            _add_moment(self.margins["windowMeans"], sum(margins) / len(margins))

    def merge(self, other):
        """Merge disjoint evaluated samples; the caller owns split/provenance checks."""
        if self.action_types != other.action_types:
            raise ValueError("cannot merge different diagnostic action types")
        self.samples += other.samples
        self.choices += other.choices
        self.forced += other.forced
        for action, item in self.items.items():
            for key in item:
                item[key].update(other.items[action][key])
        for name, item in self.margins.items():
            _merge_moments(item, other.margins[name])
        for action, strata in self.scores.items():
            for stratum, moments in strata.items():
                for name, item in moments.items():
                    _merge_moments(item, other.scores[action][stratum][name])
        return self

    def report(self):
        result = {"samples": self.samples, "choices": self.choices, "forced": self.forced,
                  "scope": "Recorded-choice agreement in action-offered choice windows; not optimal-play accuracy.",
                  "tieBreak": "First maximum in candidate order (deployed NumPy inference).",
                  "actionOrder": list(ACTIONS), "byOpportunity": {}}
        for action, item in self.items.items():
            counts = dict(item["counts"])
            denominators = {
                "precision": ("truePositive", "predictedPositive"),
                "recall": ("truePositive", "actualPositive"),
                "exactPrecision": ("exactCorrectPositive", "predictedPositive"),
                "exactPositiveRecall": ("exactCorrectPositive", "actualPositive"),
                "falseSelectionRate": ("falsePositive", "opportunityCount"),
                "exactCandidateTop1": ("exactCorrect", "opportunityCount")}
            for name, (numerator, denominator) in denominators.items():
                counts[name] = counts[numerator] / counts[denominator] if counts[denominator] else None
            negatives = counts["opportunityCount"] - counts["actualPositive"]
            counts["falsePositiveRate"] = counts["falsePositive"] / negatives if negatives else None
            confusion = {}
            for (actual, predicted), count in sorted(item["typeConfusion"].items()):
                confusion.setdefault(actual, {})[predicted] = count
            counts.update({"typeConfusion": confusion,
                           "positivePredictedOtherTypes": {
                               predicted: count for (actual, predicted), count in sorted(item["typeConfusion"].items())
                               if actual == action and predicted != action},
                           "parameterMismatches": dict(item["parameterMismatches"]),
                           "parameterMismatchPatterns": dict(item["parameterMismatchPatterns"]),
                           "parameterMismatchScope": "Type-correct but exact-wrong positives; fields overlap. RedIdentityOnly means equal base tile, different red identity; moqie includes unknown origin."})
            counts["scoreDiagnostics"] = {
                "scope": "Natural unweighted NLL and logits in focal-action opportunity windows. Strata use the recorded focal type. RecordedTypeNll sums all candidates of the recorded type; bestTypeVsOtherMargin requires another type. LogitRange.zero counts all-equal scores; tiedMaximum.positive counts windows sharing the maximum. All counted logits are finite.",
                **{stratum: {name: _finish_moments(item) for name, item in moments.items()}
                   for stratum, moments in self.scores[action].items()}}
            result["byOpportunity"][action] = counts
        if "riichi" in self.items:
            result["riichiDiscardLogitMargin"] = {
                "scope": "Riichi logit minus discard logit, identical complete parameters including red identity and moqie. AllPairs weights candidates; windowMeans weights windows; recorded pairs require the recorded candidate to be in the pair.",
                **{name: _finish_moments(item) for name, item in self.margins.items()}}
        return result
