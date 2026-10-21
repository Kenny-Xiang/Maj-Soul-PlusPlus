"""Assemble completed frozen pilot evidence; never select an epoch or deploy."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from policy_experiment_gate import evaluate_experiment


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _metric_summary(evaluation):
    diagnostics = evaluation["diagnostics"]
    return {"validationIdentity": evaluation["validationIdentity"], "metrics": evaluation["metrics"],
            "numerics": evaluation["numerics"], "diagnosticScope": evaluation["diagnosticScope"],
            "actionDiagnostics": diagnostics["byOpportunity"],
            "riichiDiscardLogitMargin": diagnostics.get("riichiDiscardLogitMargin")}


def convergence(parent, history, rules):
    """Apply the frozen descriptive plateau rules to stationary natural losses."""
    result = {"rules": rules, "globalConvergenceEstablished": False, "partitions": {}}
    intervals = rules["requiredConsecutiveIntervals"]
    for partition in ("trainMonitor", "validation"):
        points = [parent[partition]] + [entry[partition] for entry in history]
        losses = [point["metrics"]["choiceNll"] for point in points]
        recalls = [point["metrics"]["byOpportunity"]["riichi"]["recall"] for point in points]
        kan_support = [point["metrics"]["byOpportunity"]["daiminkan"]["actualPositive"] for point in points]
        enough = (len(points) > intervals and all(value is not None and math.isfinite(value)
                                                 for value in losses + recalls))
        loss_delta = [b - a for a, b in zip(losses, losses[1:])] if enough else []
        recall_delta = [b - a for a, b in zip(recalls, recalls[1:])] if enough else []
        recall_swing = max(recalls[-intervals - 1:]) - min(recalls[-intervals - 1:]) if enough else None
        plateau = (enough and all(abs(value) <= rules["naturalLossPlateauAbsoluteDelta"]
                                  for value in loss_delta[-intervals:]) and
                   recall_swing <= rules["riichiRecallMaxPlateauSwing"])
        result["partitions"][partition] = {
            "status": "insufficient_evidence" if not enough else "plateau_within_budget" if plateau else "not_plateau",
            "epochs": [0] + [entry["epoch"] for entry in history], "naturalNll": losses,
            "naturalNllDeltas": loss_delta, "riichiRecall": recalls, "riichiRecallDeltas": recall_delta,
            "riichiRecallPlateauWindowSwing": recall_swing,
            "daiminkan": {"status": "support_sufficient_for_description" if all(
                count >= rules["kanPositiveMinimumSupport"] for count in kan_support) else "insufficient_evidence",
                "actualPositive": kan_support,
                "metrics": [point["metrics"]["byOpportunity"]["daiminkan"] for point in points]}}
    result["interpretation"] = rules["interpretation"]
    result["weightedOnlineLossComparableToNaturalLoss"] = False
    return result


def _verify_evaluation(evaluation, identity, label):
    require(evaluation["validationIdentity"] == identity, label + ": partition identity differs")
    metrics, numeric = evaluation["metrics"], evaluation["numerics"]
    require(numeric["choiceWindows"] == metrics["choices"], label + ": numeric coverage differs")
    require(numeric["top1TieDisagreements"] == 0, label + ": top1 tie disagreement")
    require(all(math.isfinite(numeric[key]) for key in ("maximumAbsoluteLogit", "maximumLogitSpan")),
            label + ": nonfinite numerical diagnostic")
    for action in ("riichi", "daiminkan"):
        expected = metrics["byOpportunity"][action]
        actual = evaluation["diagnostics"]["byOpportunity"][action]
        for key in ("opportunityCount", "actualPositive", "predictedPositive", "truePositive",
                    "falsePositive", "falseNegative", "exactCorrectPositive", "exactCorrect"):
            require(actual[key] == expected[key], f"{label}: diagnostic count differs for {action}.{key}")


def _coverage(evaluation):
    metrics = evaluation["metrics"]
    return {"samples": metrics["samples"], "choices": metrics["choices"], "forced": metrics["forced"],
            "actions": {action: item["count"] for action, item in metrics["byAction"].items()},
            "opportunities": {action: {key: item[key] for key in
                ("opportunityCount", "actualPositive", "passAvailable", "passCorrect")}
                for action, item in metrics["byOpportunity"].items()}}


def _external_audits(folder, plan_path, plan_hash, v1_path):
    audits = {}
    for name in ("v1-cpu-equivalence.json", "parent-cpu-equivalence.json", "convergence-kan-audit.json",
                 "preparation-checks.json", "riichi-objective-audit.json", "daiminkan-path-audit.json",
                 "control-completion-audit.json"):
        path = folder / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text())
        audit = {"path": str(path), "sha256": sha(path), "status": data.get("status")}
        if name == "v1-cpu-equivalence.json":
            audit["sourceBindingMatches"] = (data.get("sources", {}).get(str(plan_path)) == plan_hash and
                                              data.get("sources", {}).get(str(v1_path)) == sha(v1_path))
            audit["cpuComparison"] = {key: data.get(key) for key in (
                "equivalenceLimit", "differingIntegerCounts", "globalMetrics", "naturalTrainMonitor")}
        audits[name] = audit
    return audits


def assemble(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text())
    plan_hash = sha(plan_path)
    require(plan["purpose"] == "riichi-screening-only" and plan["epochs"] == plan["primaryEpoch"] == 3,
            "Expected frozen terminal-epoch-3 screening plan")
    require(plan["testSampleReadsAllowed"] == 0 and plan["deploymentAllowed"] is False and
            plan["fullRetrainingAutomatic"] is False, "Plan scope is not screening only")
    paths = {name: Path(plan["output"]) / (name + ".json") for name in ("v1", "parent", "control", "riichi2")}
    require(all(path.is_file() for path in paths.values()), "All four phase reports must exist before assembly")
    phases = {name: json.loads(path.read_text()) for name, path in paths.items()}
    require(all(phase.get("status") == "complete" for phase in phases.values()),
            "All four phases must complete before assembly")
    for path, digest in plan["protectedSha256"].items():
        require(sha(path) == digest, "Protected input changed: " + path)
    amendment = plan.get("executionAmendment")
    if amendment:
        require(sha(amendment["priorPlan"]) == amendment["priorPlanSha256"], "Prior plan SHA differs")
    for name, phase in phases.items():
        require(phase["phase"] == name and phase["planSha256"] == plan_hash, name + ": source plan differs")
        require(phase["device"] == plan["device"] and phase["threads"] == plan["threads"],
                name + ": execution configuration differs")
        model_path = plan["v1Model"] if name == "v1" else plan["parentModel"]
        require(phase["initialModelSha256"] == plan["protectedSha256"][model_path], name + ": initial model differs")
        require(all(phase[key] == 0 for key in ("testSampleOrCacheReads", "appWrites", "cacheWrites")),
                name + ": forbidden sample read or write")
        require(phase["validationIdentity"] == plan["partitionIdentities"]["validation"],
                name + ": validation identity differs")
        expected_games = plan["validationGames"] + (plan["trainGames"] if name in plan["arms"] else plan["monitorGames"])
        require(phase["uniqueGamesRead"] == expected_games, name + ": sample access coverage differs")
        for partition, identity_name in (("validation", "validation"), ("trainMonitor", "monitor")):
            _verify_evaluation(phase[partition], plan["partitionIdentities"][identity_name], name + "." + partition)
            require(_coverage(phase[partition]) == _coverage(phases["parent"][partition]),
                    name + ": evaluation coverage differs from parent")
        if name not in plan["arms"]:
            require(phase["history"] == [], name + ": baseline unexpectedly trained")
            continue
        require([entry["epoch"] for entry in phase["history"]] == [1, 2, 3], name + ": incomplete or reordered history")
        initialization = phase["initialization"]
        require(initialization["modelOptimizerAndRngFromSameParent"] is True and
                initialization["parentResumeSha256"] == plan["protectedSha256"][plan["parentResume"]] and
                initialization["opportunityWeights"] == plan["arms"][name]["opportunityWeights"] and
                initialization["actionWeights"] == {}, name + ": initialization or treatment differs")
        for entry in phase["history"]:
            require(entry["learningRate"] == plan["learningRate"] and entry["trainChoices"] > 0 and
                    entry["optimizerSteps"] > 0, name + ": training configuration differs")
            checkpoint = Path(plan["output"]) / f"{name}.epoch-{entry['epoch']}.npz"
            require(Path(entry["checkpoint"]).resolve() == checkpoint.resolve() and
                    sha(checkpoint) == entry["checkpointSha256"], name + ": checkpoint changed")
            for partition, identity_name in (("validation", "validation"), ("trainMonitor", "monitor")):
                _verify_evaluation(entry[partition], plan["partitionIdentities"][identity_name],
                                   f"{name}.{entry['epoch']}.{partition}")
                require(_coverage(entry[partition]) == _coverage(phases["parent"][partition]),
                        name + ": epoch evaluation coverage differs from parent")
        terminal = phase["history"][-1]
        require(all(phase[key] == terminal[key] for key in ("validation", "trainMonitor")), name + ": not terminal evaluation")
        parity = phase["exportParity"]
        require(parity["samples"] > 0 and parity["argmaxAgreement"] is True and
                0 <= parity["maxAbsError"] <= 1e-4, name + ": terminal export parity failed")
        weight_audit = phase["opportunityWeightAudit"]
        require(weight_audit["windows"] == terminal["trainChoices"] and
                weight_audit["weightChanged"] == sum(weight_audit["changedByRecordedType"].values()) and
                weight_audit["riichiOffered"] == weight_audit["weightChanged"] + weight_audit["unchangedRiichiAlreadyWeighted"],
                name + ": weight audit differs from training windows")
    control, treatment = phases["control"], phases["riichi2"]
    require(control["cacheHashesSha256"] == treatment["cacheHashesSha256"], "Arms used different cached inputs")
    require(control["opportunityWeightAudit"] == treatment["opportunityWeightAudit"], "Arms changed different windows")
    for left, right in zip(control["history"], treatment["history"]):
        require(all(left[key] == right[key] for key in ("orderSha256", "trainChoices", "optimizerSteps")),
                "Arm order, choices or optimizer-step counts differ")
    require(len({entry["trainChoices"] for entry in control["history"]}) == 1,
            "Training choice coverage changed between epochs")
    gate = evaluate_experiment(treatment["validation"], control["validation"],
                               {name: phases[name]["validation"] for name in ("v1", "parent")}, plan["screeningPolicy"])
    return {"schemaVersion": 1, "status": "complete", "scope": plan["scope"],
            "plan": {"path": str(plan_path), "sha256": plan_hash, "primaryEpoch": 3,
                     "device": plan["device"], "threads": plan["threads"], "executionAmendment": amendment,
                     "partitionIdentities": plan["partitionIdentities"]},
            "provenance": {"phases": {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()},
                           "protectedSha256Verified": plan["protectedSha256"], "assemblerSha256": sha(__file__),
                           "externalAudits": _external_audits(Path(plan["output"]).parent, plan_path, plan_hash, paths["v1"]),
                           "testSampleOrCacheReads": 0, "appWrites": 0, "cacheWrites": 0},
            "screening": gate, "deploymentAllowed": False, "fullRetrainingAutomatic": False,
            "opportunityWeightAuditScope": "Both arms report the same counterfactual riichi2-versus-control affected-window audit. weightChanged counts potential differences between the two frozen weighting rules, not weights actually changed in control; control retains its baseline weights.",
            "models": {name: {"initialModelSha256": phase["initialModelSha256"],
                "validation": _metric_summary(phase["validation"]), "trainMonitor": _metric_summary(phase["trainMonitor"]),
                "history": [{**{key: value for key, value in entry.items() if key not in ("validation", "trainMonitor")},
                             "validation": _metric_summary(entry["validation"]),
                             "trainMonitor": _metric_summary(entry["trainMonitor"])} for entry in phase["history"]],
                "opportunityWeightAudit": phase.get("opportunityWeightAudit"), "exportParity": phase.get("exportParity"),
                "elapsedSeconds": phase["elapsedSeconds"]} for name, phase in phases.items()},
            "convergence": {name: convergence(phases["parent"], phases[name]["history"], plan["convergenceRules"])
                            for name in ("control", "riichi2")},
            "priorConvergenceKanAudit": str(Path(plan["output"]).parent / "convergence-kan-audit.json"),
            "interpretation": "Recorded full-action agreement on fixed public states; no playing-strength or global-convergence claim. Terminal epoch3 only determines screening; all epochs are descriptive."}


def markdown(report):
    def pct(value):
        return "无分母" if value is None else f"{100 * value:.3f}%"
    gate = report["screening"]
    text = ["# 三麻立直机会窗口对照实验", "", f"验收结果：**{gate['status']}**。主结果固定为第 3 轮；没有事后选择最优轮次。",
            "", "实验模型仅用于研究。已安装 App 未修改，测试集未读取；本报告不授权部署或自动全量重训。", "",
            "两组的机会权重审计都统计“实验规则相对对照规则可能影响的窗口”；其中的变化窗口数并不表示对照组实际加权，对照组始终保留原有权重。", "",
            f"冻结计划：`{report['plan']['sha256']}`。执行设备：{report['plan']['device']}，{report['plan']['threads']} 个计算线程。", "",
            "| 模型／轮次 | 自然验证 NLL | 总体 Top1 | 立直类型召回 | 立直完整动作召回 | 立直精确率 | 立直 FPR |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for name, model in report["models"].items():
        entries = [(name, model["validation"])] if not model["history"] else [
            (f"{name} / {entry['epoch']}", entry["validation"]) for entry in model["history"]]
        for label, evaluation in entries:
            metrics, riichi = evaluation["metrics"], evaluation["metrics"]["byOpportunity"]["riichi"]
            text.append(f"| {label} | {metrics['choiceNll']:.6f} | {pct(metrics['choiceTop1'])} | " +
                        " | ".join(pct(riichi[key]) for key in ("recall", "exactPositiveRecall", "precision", "falsePositiveRate")) + " |")
    v1_riichi = report["models"]["v1"]["validation"]["metrics"]["byOpportunity"]["riichi"]
    offers = v1_riichi["opportunityCount"]
    predicted_rate = pct(v1_riichi["predictedPositive"] / offers if offers else None)
    recorded_rate = pct(v1_riichi["actualPositive"] / offers if offers else None)
    text += ["", f"v1 在 {offers:,} 个固定公开立直机会窗口中预测立直 {v1_riichi['predictedPositive']:,} 次（{predicted_rate}），"
             f"牌谱真实立直 {v1_riichi['actualPositive']:,} 次（{recorded_rate}）。这是这些固定机会窗口中的选择频率，不是连续实战立直率；需要同时约束漏选与误选，不能只追求增加立直次数。"]
    baseline_drops = []
    v1_actions = report["models"]["v1"]["validation"]["metrics"]["byAction"]
    for action, item in report["models"]["parent"]["validation"]["metrics"]["byAction"].items():
        baseline = v1_actions.get(action)
        if baseline and item["count"] and baseline["count"]:
            delta = item["correct"] / item["count"] - baseline["correct"] / baseline["count"]
            if delta < -.003:
                baseline_drops.append(f"{action} {delta * 100:+.3f} 个百分点")
    if baseline_drops:
        text += ["", "初始 v2 相对 v1 已存在以下完整动作准确率下降：" + "、".join(baseline_drops) +
                 "。这些差异在本次处理前就存在；对 v1 的门槛失败不能自动归因于立直加权，处理效应需要看实验组与匹配对照组的差值。"]
    text += ["", "下表只统计牌谱实际选择立直的窗口，区分类型判断与完整参数。计数表示与记录选择的一致程度，不判定哪种打法最优；两组实验均使用第 3 轮。", "",
             "| 模型 | 真实立直 | 改选普通出牌 | 改选其他动作 | 选立直但参数不一致 | 完整动作一致 |",
             "|---|---:|---:|---|---:|---:|"]
    for name, model in report["models"].items():
        riichi = model["validation"]["actionDiagnostics"]["riichi"]
        misses = riichi["positivePredictedOtherTypes"]
        other = "、".join(f"{action}: {count}" for action, count in sorted(misses.items()) if action != "discard") or "0"
        text.append(f"| {name} | {riichi['actualPositive']} | {misses.get('discard', 0)} | {other} | "
                    f"{riichi['typeCorrectParameterMismatch']} | {riichi['exactCorrectPositive']} |")
    text += ["", "参数不一致总数按窗口计一次。配套 JSON 中弃牌、红牌、摸切等字段可能重叠，不能把这些字段计数直接相加。", "",
             "同一张牌、同一红牌身份、同一摸切参数下，立直分数减普通出牌分数的平均值如下。正值表示该候选对中更偏好立直；这不是和牌率或胜率，跨模型还需结合动作指标解读。", "",
             "| 模型 | 真实立直候选对：均值／数量 | 真实普通出牌候选对：均值／数量 |",
             "|---|---:|---:|"]
    for name, model in report["models"].items():
        margins = model["validation"]["riichiDiscardLogitMargin"]
        cells = []
        for key in ("recordedRiichiPair", "recordedDiscardPair"):
            item = (margins or {}).get(key, {"mean": None, "count": 0})
            mean = "无配对" if item["mean"] is None else f"{item['mean']:+.6f}"
            cells.append(f"{mean} / {item['count']}")
        text.append(f"| {name} | " + " | ".join(cells) + " |")
    text += ["", "冻结验收规则如下，直接来自本次验收记录。数值为比例或 NLL 的原始单位；最低分母要求同时适用于实验组和参照组。全部保护条件须满足，改善条件按冻结的 " +
             gate["improvementMode"] + " 规则组合。", "",
             "| 类别 | 指标 | 参照 | 门槛 | 最低分母 |", "|---|---|---|---|---:|"]
    criteria = {}
    for check in gate["checks"]:
        limit = check["tolerance"] if check["kind"] == "guard" else check["minimumDelta"]
        key = (check["kind"], check["metric"], check["againstMetric"], check["direction"], limit, check["minimumSupport"])
        criteria.setdefault(key, []).append(check["against"])
    for (kind, metric, reference_metric, direction, limit, support), references in criteria.items():
        sign = "−" if (kind == "guard") == (direction == "higher") else "+"
        operator = "≥" if direction == "higher" else "≤"
        reference = "/".join(dict.fromkeys(references)) + (f" 的 {reference_metric}" if reference_metric != metric else "")
        text.append(f"| {'保护' if kind == 'guard' else '改善'} | `{metric}` | {reference} | {operator} 参照值 {sign} {limit:g} | {support} |")
    text += ["", "以下逐项列出未通过或证据不足的条件；全部精确值、差值和分母见 JSON：", ""]
    problems = [check for check in gate["checks"] if check["status"] != "passed"]
    for check in problems:
        delta = "无法计算" if check["delta"] is None else f"{check['delta']:+.6f}"
        text.append(f"- `{check['metric']}` 对比 `{check['against']}`：{check['status']}；差值 {delta}；分母 {check['support']} / {check['referenceSupport']}。")
    if not problems:
        text.append("- 所有预先固定的验收条件均通过；仅可据此考虑后续完整训练方案。")
    text += ["", "大明杠的自然验证结果如下；可跳过子集上的模型与始终跳过基线使用相同分母。", "",
             "| 模型 | TP / FP / FN | 精确率 | 召回率 | 可跳过子集模型准确率 | 同子集始终跳过 |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, model in report["models"].items():
        kan = model["validation"]["metrics"]["byOpportunity"]["daiminkan"]
        text.append(f"| {name} | {kan['truePositive']} / {kan['falsePositive']} / {kan['falseNegative']} | " +
                    " | ".join(pct(kan[key]) for key in ("precision", "recall", "passAvailableExactCandidateTop1", "alwaysPassTop1")) + " |")
    text += ["", "收敛诊断只比较固定自然训练监测集和固定验证集；训练中的加权在线损失不与自然验证损失直接比较。", ""]
    for name, evidence in report["convergence"].items():
        for partition, values in evidence["partitions"].items():
            text.append(f"- {name} / {partition}：{values['status']}；自然 NLL 为 " +
                        " → ".join(f"{value:.6f}" for value in values["naturalNll"]) +
                        f"；大明杠正例支持状态 {values['daiminkan']['status']}。")
            if partition == "trainMonitor" and values["daiminkan"]["status"] == "insufficient_evidence":
                counts = " / ".join(str(count) for count in values["daiminkan"]["actualPositive"])
                text.append(f"  该固定监测集各检查点只有 {counts} 个大明杠正例，低于预先要求的 {evidence['rules']['kanPositiveMinimumSupport']} 个，不能据此判断大明杠已收敛。")
    text += ["", "平台期判定采用冻结计划中的最后两个连续区间和立直召回波动限制。三轮小规模继续训练不足以证明整体训练已收敛。", "",
             "实验边界：两组只使用单一父模型及随机状态、固定训练划分的前 2,048 场，没有跨种子或子集重复；4,706 场验证集已在此前研究中被反复查看。512 场自然监测集属于本次训练子集，作用是固定口径观察拟合；同一牌局内的窗口不是相互独立的样本。本次结果仅用于判断是否值得制定完整训练方案，不是独立泛化证明或部署验收。", "",
             "上述准确率衡量与公开牌谱真实选择的一致程度，不代表最优打法或实战强度。分动作混淆、参数错误、正负例 NLL、同牌立直分差、数值范围及每轮模型哈希均保存在配套 JSON 中。", ""]
    if report["plan"]["executionAmendment"]:
        text += ["MPS 在读取语料及真实训练前的设备预检阶段不可用，因此预先修订为 CPU。设备速度测试使用合成输入，不属于模型训练或选模。", ""]
    audits = report["provenance"].get("externalAudits", {})
    cpu = audits.get("v1-cpu-equivalence.json", {})
    if cpu.get("sourceBindingMatches"):
        comparison = cpu["cpuComparison"]
        discard = next((item for item in comparison["differingIntegerCounts"]
                        if item["path"] == "byAction.discard.correct"), None)
        if discard:
            nll_delta = comparison["globalMetrics"]["choiceNll"]["difference"]
            text += [f"CPU 重算的 v1 与历史基线并非计数完全相同：普通出牌完整动作正确数变化 {discard['difference']:+d}，自然 NLL 差值 {nll_delta:+.3e}。本实验统一使用此次 CPU 基线；聚合统计不能确定所有逐条预测是否相同，也不能单凭它确定差异原因。", ""]
    if audits:
        text += ["补充审计证据及文件哈希：", ""]
        text += [f"- [{name}]({audit['path']})：`{audit['sha256']}`。" for name, audit in audits.items()]
        text.append("")
    return "\n".join(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, default=ROOT / "docs/benchmarks/riichi-pilot-20261016.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "docs/riichi-pilot-20261016.md")
    args = parser.parse_args()
    require(not args.json_output.exists() and not args.markdown_output.exists(), "Preserve existing assembled reports")
    report = assemble(args.plan)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    readable = markdown(report)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(serialized)
    args.markdown_output.write_text(readable)
    print(json.dumps({"status": report["screening"]["status"], "json": str(args.json_output),
                      "markdown": str(args.markdown_output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
