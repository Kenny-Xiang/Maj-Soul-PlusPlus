"""Screen a matched pilot on natural validation; never authorize deployment.

Each result is {"validationIdentity": <frozen subset hash>, "metrics": <evaluate result>}.
Policy guards specify metric, direction, tolerance, minimumSupport and against.
Improvement rules replace tolerance with minimumDelta. All limits are supplied by
the frozen experiment policy, not chosen from observed results.
"""
import math


OPPORTUNITY_RATIOS = {
    "precision": ("truePositive", "predictedPositive"),
    "recall": ("truePositive", "actualPositive"),
    "exactPositiveRecall": ("exactCorrectPositive", "actualPositive"),
    "falsePositiveRate": ("falsePositive", "actualNegative"),
    "falseSelectionRate": ("falsePositive", "opportunityCount"),
    "exactCandidateTop1": ("exactCorrect", "opportunityCount"),
    "alwaysPassTop1": ("passCorrect", "passAvailable"),
    "passAvailableExactCandidateTop1": ("passAvailableExactCorrect", "passAvailable"),
}
OPPORTUNITY_COUNTS = {
    "opportunityCount", "actualPositive", "predictedPositive", "truePositive",
    "exactCorrectPositive", "falsePositive", "falseNegative", "exactCorrect",
    "passAvailable", "passCorrect", "passAvailableExactCorrect",
}


def _count(value):
    return type(value) is int and value >= 0


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _measure(metrics, path):
    parts = path.split(".")
    if len(parts) == 1 and path in ("choiceNll", "choiceTop1", "choiceTop3"):
        value, support = metrics.get(path), metrics.get("choices")
        return value if _finite(value) else None, support
    if len(parts) == 3 and parts[0] == "byAction" and parts[2] == "accuracy":
        item = metrics.get("byAction", {}).get(parts[1], {})
        numerator, support = item.get("correct"), item.get("count")
    elif len(parts) == 3 and parts[0] == "byOpportunity" and parts[2] in OPPORTUNITY_RATIOS:
        item = dict(metrics.get("byOpportunity", {}).get(parts[1], {}))
        if _count(item.get("opportunityCount")) and _count(item.get("actualPositive")):
            item["actualNegative"] = item["opportunityCount"] - item["actualPositive"]
        numerator_name, denominator_name = OPPORTUNITY_RATIOS[parts[2]]
        numerator, support = item.get(numerator_name), item.get(denominator_name)
    else:
        raise ValueError(f"Unsupported gate metric: {path}")
    value = numerator / support if _count(numerator) and _count(support) and support else None
    return value, support


def _evidence_issues(results):
    """Separate absent evidence from contradictory evidence before comparing rates."""
    issues, signatures = [], {}
    for name, result in results.items():
        metrics = result.get("metrics", {})
        identity = result.get("validationIdentity")
        if not isinstance(identity, str) or not identity:
            issues.append({"status": "insufficient_evidence", "reason": f"{name}: missing validation identity"})
        invariants = {"validationIdentity": identity}
        for key in ("samples", "choices", "forced"):
            value = metrics.get(key)
            if value is None:
                issues.append({"status": "insufficient_evidence", "reason": f"{name}: missing {key}"})
            elif not _count(value):
                issues.append({"status": "invalid_evidence", "reason": f"{name}: invalid {key}"})
            invariants[key] = value
        if all(_count(metrics.get(key)) for key in ("samples", "choices", "forced")):
            if metrics["samples"] != metrics["choices"] + metrics["forced"]:
                issues.append({"status": "invalid_evidence", "reason": f"{name}: samples != choices + forced"})
        for key in ("choiceNll", "choiceTop1", "choiceTop3"):
            value = metrics.get(key)
            if value is not None and (not _finite(value) or value < 0 or key != "choiceNll" and value > 1):
                issues.append({"status": "invalid_evidence", "reason": f"{name}: invalid {key}"})
        for action, item in metrics.get("byAction", {}).items():
            invariants[f"byAction.{action}.count"] = item.get("count")
            if not all(_count(item.get(key)) for key in ("count", "correct")):
                issues.append({"status": "insufficient_evidence", "reason": f"{name}: missing action counts for {action}"})
            elif item["correct"] > item["count"]:
                issues.append({"status": "invalid_evidence", "reason": f"{name}: correct exceeds count for {action}"})
        for action, item in metrics.get("byOpportunity", {}).items():
            for key in ("opportunityCount", "actualPositive", "passAvailable", "passCorrect"):
                invariants[f"byOpportunity.{action}.{key}"] = item.get(key)
            if not all(_count(item.get(key)) for key in OPPORTUNITY_COUNTS):
                issues.append({"status": "insufficient_evidence", "reason": f"{name}: missing opportunity counts for {action}"})
                continue
            coherent = (
                item["actualPositive"] == item["truePositive"] + item["falseNegative"] and
                item["predictedPositive"] == item["truePositive"] + item["falsePositive"] and
                item["actualPositive"] + item["falsePositive"] <= item["opportunityCount"] and
                item["exactCorrectPositive"] <= item["truePositive"] <= item["predictedPositive"] <= item["opportunityCount"] and
                item["exactCorrectPositive"] <= item["exactCorrect"] <= item["opportunityCount"] and
                item["exactCorrect"] <= item["exactCorrectPositive"] + item["opportunityCount"] - item["actualPositive"] - item["falsePositive"] and
                item["passCorrect"] <= item["passAvailable"] <= item["opportunityCount"] and
                item["passAvailableExactCorrect"] <= min(item["passAvailable"], item["exactCorrect"]))
            if not coherent:
                issues.append({"status": "invalid_evidence", "reason": f"{name}: inconsistent opportunity counts for {action}"})
        signatures[name] = invariants
    first = signatures["treatment"]
    for name, signature in signatures.items():
        if name == "treatment":
            continue
        keys = set(first) | set(signature)
        missing = sorted(key for key in keys if first.get(key) is None or signature.get(key) is None)
        if missing:
            issues.append({"status": "insufficient_evidence", "reason": f"{name}: missing invariant evidence",
                           "fields": missing})
        differing = sorted(key for key in keys - set(missing) if first[key] != signature[key])
        if differing:
            issues.append({"status": "invalid_evidence", "reason": f"{name}: validation subset or invariant counts differ",
                           "fields": differing})
    return issues


def evaluate_experiment(treatment, control, references, policy):
    """Return all guard/improvement deltas and a screening-only disposition.

    Rules may use againstMetric for a same-subset always-pass comparison. Support
    is the actual denominator of each metric, checked on both compared models.
    Missing support never becomes a pass, even when improvementMode is 'any'.
    """
    if set(references) != {"v1", "parent"}:
        raise ValueError("references must contain same-subset v1 and parent results")
    results = {"treatment": treatment, "control": control, **references}
    if policy.get("improvementMode") not in ("any", "all"):
        raise ValueError("improvementMode must be explicitly any or all")
    if not policy.get("guards") or not policy.get("improvements"):
        raise ValueError("nonempty guards and improvements are required")
    checks = []
    for kind, rules in (("guard", policy["guards"]), ("improvement", policy["improvements"])):
        limit_name = "tolerance" if kind == "guard" else "minimumDelta"
        for rule in rules:
            limit = rule.get(limit_name)
            support = rule.get("minimumSupport")
            if (rule.get("direction") not in ("higher", "lower") or not _finite(limit) or limit < 0 or
                    not _count(support) or support == 0 or not rule.get("against") or
                    any(name not in ("v1", "parent", "control") for name in rule["against"])):
                raise ValueError(f"Invalid explicit {kind} rule: {rule}")
            path = rule["metric"]
            reference_path = rule.get("againstMetric", path)
            value, denominator = _measure(treatment.get("metrics", {}), path)
            for name in rule["against"]:
                baseline, baseline_denominator = _measure(results[name].get("metrics", {}), reference_path)
                delta = value - baseline if value is not None and baseline is not None else None
                sufficient = (delta is not None and _count(denominator) and denominator >= support and
                              _count(baseline_denominator) and baseline_denominator >= support)
                favorable = delta if rule["direction"] == "higher" else -delta if delta is not None else None
                passed = sufficient and favorable >= (-limit if kind == "guard" else limit) - 1e-12
                status = "passed" if passed else "failed" if sufficient else "insufficient_evidence"
                checks.append({"kind": kind, "metric": path, "against": name, "againstMetric": reference_path,
                               "direction": rule["direction"], limit_name: limit, "minimumSupport": support,
                               "value": value, "referenceValue": baseline, "delta": delta,
                               "support": denominator, "referenceSupport": baseline_denominator,
                               "status": status, "reason": ("within frozen criterion" if passed else
                                   "outside frozen criterion" if sufficient else "missing or insufficient denominator/value")})
    issues = _evidence_issues(results)
    guard_passed = all(check["status"] == "passed" for check in checks if check["kind"] == "guard")
    improvements = [check["status"] == "passed" for check in checks if check["kind"] == "improvement"]
    improved = (any if policy["improvementMode"] == "any" else all)(improvements)
    if any(issue["status"] == "invalid_evidence" for issue in issues):
        status = "invalid_evidence"
    elif issues or any(check["status"] == "insufficient_evidence" for check in checks):
        status = "insufficient_evidence"
    else:
        status = "passed_screening" if guard_passed and improved else "rejected"
    return {"status": status, "scope": "matched pilot screening for full retraining; not deployment acceptance",
            "recommendFullRetrain": status == "passed_screening", "deployable": False,
            "validationIdentity": treatment.get("validationIdentity"), "improvementMode": policy["improvementMode"],
            "checks": checks, "evidenceIssues": issues}
