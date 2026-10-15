# 三麻、四麻监督模仿模型 v2：固定实验验证未通过（2026-10-15）

固定三麻 12 个检查点、四麻 8 个检查点已完成验证；3、4 麻没有符合既定全部门槛的检查点。整体状态为 `validation-rejected`，未接受模型、未冻结最终选择、未开启新模型 test，也未替换已安装 App。

逐动作存在明显退步：四麻诊断锚点的立直完整动作召回从 71.459% 降至 63.854%（下降 7.605 个百分点，37,385 个真实立直中少命中 2,843 个）；三麻加杠从 79.068% 降至 76.969%（下降 2.100 个百分点，1,524 个真实加杠中少命中 32 个）。两类动作同时出现误选减少与真实动作漏判增加，整体 Top1／NLL 改善不能代表每类动作都改善。

大明杠仍未解决：四麻在同一批 12,635 个 pass 合法的机会中，模型完整动作正确 11,677 次，始终 pass 正确 11,689 次，模型少对 12 次；三麻 control 与四麻诊断锚点的大明杠 precision 分别为 35.897%、39.785%，均未达到 50% 门槛。

三麻两臂第 2 轮自然验证 NLL 仅相差 2.882e-08，不足以声称可重复的泛化优势。label2 相对 control 多命中 32 个真实大明杠，也多误选 67 次；在相同 9,769 个机会中完整动作正确数反而减少 34，下降 0.348 个百分点，超过 0.300 个百分点的既定容许降幅。因此召回提升没有解决误选权衡。

研究始于 2026-10-13，文件名保留起始日期。学习目标仍是当前可见局面到高段位玩家真实完整动作的监督模仿，不使用收益、价值或强化学习目标。仅使用既定公开三麻 47,063 场和四麻 49,951 场；没有补充个人或 App 牌谱，没有更改整场 train／validation／test 归属。

v2 移除 `round_count/2` 和 `round_count_known`，全局特征 56→54，参数 756,545→756,033；不新增局次、末局或距结束局数。保留场风、自风、公开点数、已公开宝牌与杠宝牌、赤牌、公开拔北数、手牌、河牌、副露及完整合法动作参数。三四麻权重独立。

以下每种玩法的比较锚点只按固定池最低自然验证 NLL 确定，用于解释结果和可选的离线兼容研究，**不是接受模型**。即使某玩法单独存在合格检查点，双模型交付仍未通过。已知旧 v1 历史 test 不在本报告中重新读取或评价。

## 完整验证集：v1 与未接受的诊断锚点

| 玩法 | 诊断阶段／轮次 | choice 数 | v1／v2 Top1 | v1／v2 Top3 | v1／v2 NLL | v1／v2 出牌 | 锚点自身合格 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 3 麻 | control / 2 | 1,491,635 | 75.442% / 76.264% | 95.690% / 96.173% | 0.670240 / 0.641313 | 71.371% / 72.343% | False（仍未接受） |
| 4 麻 | original / 8 | 3,002,766 | 73.542% / 74.231% | 94.854% / 95.226% | 0.727377 / 0.703465 | 68.426% / 69.354% | False（仍未接受） |

### 3 麻十二类完整动作与合法机会

| 动作 | v1 完整正确／支持 | 诊断锚点完整正确／支持 |
| --- | ---: | ---: |
| 出牌 | 840,092 / 1,177,074（71.371%） | 851,532 / 1,177,074（72.343%） |
| 立直 | 19,302 / 29,987（64.368%） | 19,059 / 29,987（63.558%） |
| 吃 | 不适用 | 不适用 |
| 碰 | 30,626 / 39,006（78.516%） | 32,031 / 39,006（82.118%） |
| 大明杠 | 1 / 224（0.446%） | 14 / 224（6.250%） |
| 暗杠 | 1,974 / 2,728（72.361%） | 1,996 / 2,728（73.167%） |
| 加杠 | 1,205 / 1,524（79.068%） | 1,173 / 1,524（76.969%） |
| 拔北 | 104,294 / 106,624（97.815%） | 104,174 / 106,624（97.702%） |
| 自摸 | 16,397 / 16,397（100.000%） | 16,396 / 16,397（99.994%） |
| 荣和 | 16,381 / 16,383（99.988%） | 16,382 / 16,383（99.994%） |
| 九种九牌流局 | 1,300 / 1,312（99.085%） | 1,292 / 1,312（98.476%） |
| 跳过 | 93,745 / 100,376（93.394%） | 93,525 / 100,376（93.175%） |

机会统计只用至少两个合法候选的窗口。类型 TP／precision 合并同动作类型的红牌与消耗组合，精确召回仍比较完整候选。FPR 的分母是实际负例；模型／始终 pass 都限制在 pass 合法的同一子集。

| 动作 | 版本 | 机会／阳性／预测 | TP／FP | 精确召回 | precision | FPR | 条件完整 Top1 | pass 子集数 | 模型／始终 pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 出牌 | v1 | 1321917 / 1177074 / 1170661 | 1159610 / 11051 | 71.371% | 99.056% | 7.630% | 73.442% | 0 | 不适用 / 不适用 |
| 出牌 | 诊断锚点 | 1321917 / 1177074 / 1174094 | 1162326 / 11768 | 72.343% | 98.998% | 8.125% | 74.278% | 0 | 不适用 / 不适用 |
| 立直 | v1 | 100270 / 29987 / 32442 | 21472 / 10970 | 64.368% | 66.186% | 15.608% | 65.023% | 0 | 不适用 / 不适用 |
| 立直 | 诊断锚点 | 100270 / 29987 / 30067 | 20923 / 9144 | 63.558% | 69.588% | 13.010% | 67.098% | 0 | 不适用 / 不适用 |
| 吃 | v1 | 不适用 | — | — | — | — | — | — | — |
| 吃 | 诊断锚点 | 不适用 | — | — | — | — | — | — | — |
| 碰 | v1 | 141653 / 39006 / 37037 | 30626 / 6411 | 78.516% | 82.690% | 6.246% | 89.378% | 141653 | 89.378% / 70.727% |
| 碰 | 诊断锚点 | 141653 / 39006 / 38642 | 32031 / 6611 | 82.118% | 82.892% | 6.441% | 90.224% | 141653 | 90.224% / 70.727% |
| 大明杠 | v1 | 9769 / 224 / 2 | 1 / 1 | 0.446% | 50.000% | 0.010% | 93.776% | 9769 | 93.776% / 92.794% |
| 大明杠 | 诊断锚点 | 9769 / 224 / 39 | 14 / 25 | 6.250% | 35.897% | 0.262% | 94.268% | 9769 | 94.268% / 92.794% |
| 暗杠 | v1 | 17551 / 2728 / 3067 | 1974 / 1093 | 72.361% | 64.363% | 7.374% | 70.030% | 757 | 96.169% / 3.699% |
| 暗杠 | 诊断锚点 | 17551 / 2728 / 2864 | 1997 / 867 | 73.167% | 69.728% | 5.849% | 71.654% | 757 | 96.169% / 3.699% |
| 加杠 | v1 | 5544 / 1524 / 1831 | 1205 / 626 | 79.068% | 65.811% | 15.572% | 72.258% | 0 | 不适用 / 不适用 |
| 加杠 | 诊断锚点 | 5544 / 1524 / 1687 | 1173 / 514 | 76.969% | 69.532% | 12.786% | 73.377% | 0 | 不适用 / 不适用 |
| 拔北 | v1 | 127865 / 106624 / 109670 | 104948 / 4722 | 97.815% | 95.694% | 22.231% | 89.970% | 4258 | 99.460% / 0.540% |
| 拔北 | 诊断锚点 | 127865 / 106624 / 108998 | 104813 / 4185 | 97.702% | 96.160% | 19.702% | 90.248% | 4258 | 99.460% / 0.540% |
| 自摸 | v1 | 16511 / 16397 / 16511 | 16397 / 114 | 100.000% | 99.310% | 100.000% | 99.310% | 8791 | 99.852% / 0.148% |
| 自摸 | 诊断锚点 | 16511 / 16397 / 16508 | 16396 / 112 | 99.994% | 99.322% | 98.246% | 99.310% | 8791 | 99.852% / 0.148% |
| 荣和 | v1 | 16543 / 16383 / 16541 | 16381 / 160 | 99.988% | 99.033% | 100.000% | 99.021% | 16543 | 99.021% / 0.955% |
| 荣和 | 诊断锚点 | 16543 / 16383 / 16540 | 16382 / 158 | 99.994% | 99.045% | 98.750% | 99.039% | 16543 | 99.039% / 0.955% |
| 九种九牌流局 | v1 | 1563 / 1312 / 1527 | 1300 / 227 | 99.085% | 85.134% | 90.438% | 84.069% | 0 | 不适用 / 不适用 |
| 九种九牌流局 | 诊断锚点 | 1563 / 1312 / 1491 | 1292 / 199 | 98.476% | 86.653% | 79.283% | 84.325% | 0 | 不适用 / 不适用 |
| 跳过 | v1 | 169718 / 100376 / 102346 | 93745 / 8601 | 93.394% | 91.596% | 12.404% | 91.022% | 169718 | 91.022% / 59.143% |
| 跳过 | 诊断锚点 | 169718 / 100376 / 100705 | 93525 / 7180 | 93.175% | 92.870% | 10.354% | 91.729% | 169718 | 91.729% / 59.143% |

### 4 麻十二类完整动作与合法机会

| 动作 | v1 完整正确／支持 | 诊断锚点完整正确／支持 |
| --- | ---: | ---: |
| 出牌 | 1,576,766 / 2,304,326（68.426%） | 1,598,134 / 2,304,326（69.354%） |
| 立直 | 26,715 / 37,385（71.459%） | 23,872 / 37,385（63.854%） |
| 吃 | 16,982 / 40,258（42.183%） | 19,256 / 40,258（47.831%） |
| 碰 | 43,268 / 58,538（73.914%） | 45,847 / 58,538（78.320%） |
| 大明杠 | 2 / 375（0.533%） | 37 / 375（9.867%） |
| 暗杠 | 1,432 / 2,317（61.804%） | 1,545 / 2,317（66.681%） |
| 加杠 | 1,125 / 1,630（69.018%） | 1,217 / 1,630（74.663%） |
| 拔北 | 不适用 | 不适用 |
| 自摸 | 16,355 / 16,355（100.000%） | 16,355 / 16,355（100.000%） |
| 荣和 | 25,545 / 25,546（99.996%） | 25,540 / 25,546（99.977%） |
| 九种九牌流局 | 498 / 505（98.614%） | 496 / 505（98.218%） |
| 跳过 | 499,618 / 515,531（96.913%） | 496,691 / 515,531（96.346%） |

机会统计只用至少两个合法候选的窗口。类型 TP／precision 合并同动作类型的红牌与消耗组合，精确召回仍比较完整候选。FPR 的分母是实际负例；模型／始终 pass 都限制在 pass 合法的同一子集。

| 动作 | 版本 | 机会／阳性／预测 | TP／FP | 精确召回 | precision | FPR | 条件完整 Top1 | pass 子集数 | 模型／始终 pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 出牌 | v1 | 2353515 / 2304326 / 2296461 | 2287567 / 8894 | 68.426% | 99.613% | 18.081% | 68.574% | 0 | 不适用 / 不适用 |
| 出牌 | 诊断锚点 | 2353515 / 2304326 / 2304569 | 2292284 / 12285 | 69.354% | 99.467% | 24.975% | 69.369% | 0 | 不适用 / 不适用 |
| 立直 | v1 | 98959 / 37385 / 44931 | 29800 / 15131 | 71.459% | 66.324% | 24.574% | 63.358% | 0 | 不适用 / 不适用 |
| 立直 | 诊断锚点 | 98959 / 37385 / 36477 | 26226 / 10251 | 63.854% | 71.897% | 16.648% | 64.363% | 0 | 不适用 / 不适用 |
| 吃 | v1 | 401574 / 40258 / 24041 | 18439 / 5602 | 42.183% | 76.698% | 1.550% | 92.626% | 401574 | 92.626% / 88.795% |
| 吃 | 诊断锚点 | 401574 / 40258 / 28231 | 21071 / 7160 | 47.831% | 74.638% | 1.982% | 92.801% | 401574 | 92.801% / 88.795% |
| 碰 | v1 | 233546 / 58538 / 53455 | 43275 / 10180 | 73.914% | 80.956% | 5.817% | 88.702% | 233546 | 88.702% / 73.334% |
| 碰 | 诊断锚点 | 233546 / 58538 / 57385 | 45856 / 11529 | 78.320% | 79.909% | 6.588% | 89.225% | 233546 | 89.225% / 73.334% |
| 大明杠 | v1 | 12635 / 375 / 13 | 2 / 11 | 0.533% | 15.385% | 0.090% | 92.291% | 12635 | 92.291% / 92.513% |
| 大明杠 | 诊断锚点 | 12635 / 375 / 93 | 37 / 56 | 9.867% | 39.785% | 0.457% | 92.418% | 12635 | 92.418% / 92.513% |
| 暗杠 | v1 | 15371 / 2317 / 2272 | 1433 / 839 | 61.804% | 63.072% | 6.427% | 65.767% | 473 | 98.732% / 1.057% |
| 暗杠 | 诊断锚点 | 15371 / 2317 / 2452 | 1545 / 907 | 66.681% | 63.010% | 6.948% | 66.866% | 473 | 98.943% / 1.057% |
| 加杠 | v1 | 7115 / 1630 / 1801 | 1126 / 675 | 69.018% | 62.521% | 12.306% | 69.178% | 0 | 不适用 / 不适用 |
| 加杠 | 诊断锚点 | 7115 / 1630 / 1972 | 1218 / 754 | 74.663% | 61.765% | 13.747% | 69.754% | 0 | 不适用 / 不适用 |
| 拔北 | v1 | 不适用 | — | — | — | — | — | — | — |
| 拔北 | 诊断锚点 | 不适用 | — | — | — | — | — | — | — |
| 自摸 | v1 | 16433 / 16355 / 16433 | 16355 / 78 | 100.000% | 99.525% | 100.000% | 99.525% | 8538 | 99.965% / 0.035% |
| 自摸 | 诊断锚点 | 16433 / 16355 / 16433 | 16355 / 78 | 100.000% | 99.525% | 100.000% | 99.525% | 8538 | 99.965% / 0.035% |
| 荣和 | v1 | 25753 / 25546 / 25751 | 25545 / 206 | 99.996% | 99.200% | 99.517% | 99.196% | 25753 | 99.196% / 0.780% |
| 荣和 | 诊断锚点 | 25753 / 25546 / 25745 | 25540 / 205 | 99.977% | 99.204% | 99.034% | 99.181% | 25753 | 99.181% / 0.780% |
| 九种九牌流局 | v1 | 644 / 505 / 627 | 498 / 129 | 98.614% | 79.426% | 92.806% | 77.950% | 0 | 不适用 / 不适用 |
| 九种九牌流局 | 诊断锚点 | 644 / 505 / 623 | 496 / 127 | 98.218% | 79.615% | 91.367% | 78.261% | 0 | 不适用 / 不适用 |
| 跳过 | v1 | 649251 / 515531 / 536981 | 499618 / 37363 | 96.913% | 93.042% | 27.941% | 91.554% | 649251 | 91.554% / 79.404% |
| 跳过 | 诊断锚点 | 649251 / 515531 / 528786 | 496691 / 32095 | 96.346% | 93.930% | 24.002% | 91.856% | 649251 | 91.856% / 79.404% |

## 逐轮验证与选模

数值门槛保持冻结策略：自然频率 NLL、整体／出牌完整候选准确率、五类机会准确率，以及预测至少 10 次时类型 precision。少于 10 次预测属于稀疏观察，不据此拒绝，也不算已证明该动作可靠。合格者按七类至少 100 个验证正例的平均精确召回排序，随后按较低 NLL 破平。不能用整体 NLL 代替逐动作验收。

三麻候选池在后续对照开始前固定为原 8 轮、control 2 轮和 label2 2 轮，共 12 个检查点。参考为全池最低自然验证 NLL；每个候选必须同时满足相对该参考和原第 8 轮父模型的全部既定门槛。最终仍相同时按 original／control／label2、较早阶段轮次排序。四麻保持原 8 轮及原策略。

下表同时保留各阶段内部参考下的失败项；最终是否合格依据固定候选池与父模型两组门槛。两条后续分支分别从同一个父模型开始，阶段第 1、2 轮对应各自累计第 9、10 轮；不会把两臂累加成单条模型的 12 轮。

| 玩法 | 阶段 | 阶段轮次 | 累计轮次 | LR | 训练 loss | 验证 NLL | Top1 | Top3 | 出牌 | 大明杠 TP／预测 | 大明杠精确召回／precision | 未过门槛 | 选中 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 3 麻 | original | 1 | 1 | 0.001 | 0.782368 | 0.709907 | 74.365% | 95.035% | 70.276% | 0 / 19 | 0.000% / 0.000% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:pon:opportunityExactTop1；阶段内:daiminkan:opportunityExactTop1；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1；固定池:naturalNll；固定池:overallExactTop1；固定池:discardExactAccuracy；固定池:pon:opportunityExactTop1；固定池:daiminkan:opportunityExactTop1；固定池:daiminkan:precision；固定池:ankan:opportunityExactTop1；固定池:shouminkan:opportunityExactTop1；父e8:naturalNll；父e8:overallExactTop1；父e8:discardExactAccuracy；父e8:pon:opportunityExactTop1；父e8:daiminkan:opportunityExactTop1；父e8:daiminkan:precision；父e8:ankan:opportunityExactTop1；父e8:shouminkan:opportunityExactTop1 |  |
| 3 麻 | original | 2 | 2 | 0.000955436 | 0.668215 | 0.687371 | 75.054% | 95.397% | 71.081% | 1 / 6 | 0.446% / 16.667% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:pon:opportunityExactTop1；阶段内:daiminkan:opportunityExactTop1；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1；固定池:naturalNll；固定池:overallExactTop1；固定池:discardExactAccuracy；固定池:pon:opportunityExactTop1；固定池:daiminkan:opportunityExactTop1；固定池:ankan:opportunityExactTop1；固定池:shouminkan:opportunityExactTop1；父e8:naturalNll；父e8:overallExactTop1；父e8:discardExactAccuracy；父e8:pon:opportunityExactTop1；父e8:daiminkan:opportunityExactTop1；父e8:ankan:opportunityExactTop1；父e8:shouminkan:opportunityExactTop1 |  |
| 3 麻 | original | 3 | 3 | 0.00083057 | 0.648103 | 0.672305 | 75.453% | 95.623% | 71.268% | 3 / 14 | 1.339% / 21.429% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:pon:opportunityExactTop1；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1；固定池:naturalNll；固定池:overallExactTop1；固定池:discardExactAccuracy；固定池:pon:opportunityExactTop1；固定池:daiminkan:precision；固定池:ankan:opportunityExactTop1；固定池:shouminkan:opportunityExactTop1；父e8:naturalNll；父e8:overallExactTop1；父e8:discardExactAccuracy；父e8:pon:opportunityExactTop1；父e8:daiminkan:precision；父e8:ankan:opportunityExactTop1；父e8:shouminkan:opportunityExactTop1 |  |
| 3 麻 | original | 4 | 4 | 0.000650134 | 0.633620 | 0.661723 | 75.668% | 95.837% | 71.473% | 1 / 5 | 0.446% / 20.000% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:pon:opportunityExactTop1；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1；固定池:naturalNll；固定池:overallExactTop1；固定池:discardExactAccuracy；固定池:pon:opportunityExactTop1；固定池:ankan:opportunityExactTop1；固定池:shouminkan:opportunityExactTop1；父e8:naturalNll；父e8:overallExactTop1；父e8:discardExactAccuracy；父e8:pon:opportunityExactTop1；父e8:ankan:opportunityExactTop1；父e8:shouminkan:opportunityExactTop1 |  |
| 3 麻 | original | 5 | 5 | 0.000449866 | 0.621582 | 0.653840 | 75.912% | 95.951% | 71.872% | 3 / 11 | 1.339% / 27.273% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；固定池:naturalNll；固定池:overallExactTop1；固定池:discardExactAccuracy；固定池:daiminkan:precision；固定池:ankan:opportunityExactTop1；父e8:naturalNll；父e8:overallExactTop1；父e8:discardExactAccuracy；父e8:daiminkan:precision；父e8:ankan:opportunityExactTop1 |  |
| 3 麻 | original | 6 | 6 | 0.00026943 | 0.611632 | 0.646955 | 76.114% | 96.079% | 72.097% | 5 / 15 | 2.232% / 33.333% | 阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；固定池:naturalNll；固定池:discardExactAccuracy；固定池:daiminkan:precision；固定池:ankan:opportunityExactTop1；固定池:shouminkan:opportunityExactTop1；父e8:daiminkan:precision；父e8:ankan:opportunityExactTop1 |  |
| 3 麻 | original | 7 | 7 | 0.000144564 | 0.604492 | 0.643732 | 76.230% | 96.126% | 72.167% | 11 / 31 | 4.911% / 35.484% | 阶段内:daiminkan:precision；固定池:daiminkan:precision；父e8:daiminkan:precision |  |
| 3 麻 | original | 8 | 8 | 0.0001 | 0.600961 | 0.642425 | 76.275% | 96.143% | 72.255% | 11 / 33 | 4.911% / 33.333% | 阶段内:daiminkan:precision；固定池:daiminkan:precision；父e8:daiminkan:precision |  |
| 3 麻 | control | 1 | 9 | 0.0001 | 0.599624 | 0.641498 | 76.270% | 96.165% | 72.246% | 7 / 30 | 3.125% / 23.333% | 阶段内:daiminkan:precision；固定池:daiminkan:precision；父e8:daiminkan:precision |  |
| 3 麻 | control | 2 | 10 | 0.0001 | 0.598468 | 0.641313 | 76.264% | 96.173% | 72.343% | 14 / 39 | 6.250% / 35.897% | 阶段内:daiminkan:precision；固定池:daiminkan:precision；父e8:daiminkan:precision |  |
| 3 麻 | label2 | 1 | 9 | 0.0001 | 0.600303 | 0.641627 | 76.270% | 96.164% | 72.243% | 34 / 106 | 15.179% / 32.075% | 阶段内:daiminkan:precision；固定池:daiminkan:precision；父e8:daiminkan:precision |  |
| 3 麻 | label2 | 2 | 10 | 0.0001 | 0.599109 | 0.641313 | 76.264% | 96.171% | 72.348% | 46 / 138 | 20.536% / 33.333% | 阶段内:daiminkan:precision；固定池:daiminkan:opportunityExactTop1；固定池:daiminkan:precision；父e8:daiminkan:opportunityExactTop1；父e8:daiminkan:precision |  |
| 4 麻 | original | 1 | 1 | 0.001 | 0.825824 | 0.754564 | 72.709% | 94.406% | 67.466% | 6 / 21 | 1.600% / 28.571% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:chi:opportunityExactTop1；阶段内:pon:opportunityExactTop1；阶段内:daiminkan:opportunityExactTop1；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1 |  |
| 4 麻 | original | 2 | 2 | 0.001 | 0.740586 | 0.733878 | 73.326% | 94.744% | 68.135% | 6 / 39 | 1.600% / 15.385% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:pon:opportunityExactTop1；阶段内:daiminkan:opportunityExactTop1；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1 |  |
| 4 麻 | original | 3 | 3 | 0.001 | 0.726257 | 0.726216 | 73.555% | 94.868% | 68.482% | 7 / 24 | 1.867% / 29.167% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:pon:opportunityExactTop1；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1 |  |
| 4 麻 | original | 4 | 4 | 0.001 | 0.717827 | 0.718092 | 73.787% | 94.990% | 68.715% | 22 / 41 | 5.867% / 53.659% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1 |  |
| 4 麻 | original | 5 | 5 | 0.001 | 0.711947 | 0.714339 | 73.894% | 95.074% | 68.881% | 5 / 23 | 1.333% / 21.739% | 阶段内:naturalNll；阶段内:overallExactTop1；阶段内:discardExactAccuracy；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1 |  |
| 4 麻 | original | 6 | 6 | 0.001 | 0.707092 | 0.708902 | 74.103% | 95.148% | 69.065% | 14 / 35 | 3.733% / 40.000% | 阶段内:naturalNll；阶段内:discardExactAccuracy；阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1；阶段内:shouminkan:opportunityExactTop1 |  |
| 4 麻 | original | 7 | 7 | 0.001 | 0.702945 | 0.706167 | 74.195% | 95.178% | 69.223% | 9 / 37 | 2.400% / 24.324% | 阶段内:daiminkan:precision；阶段内:ankan:opportunityExactTop1 |  |
| 4 麻 | original | 8 | 8 | 0.001 | 0.699247 | 0.703465 | 74.231% | 95.226% | 69.354% | 37 / 93 | 9.867% / 39.785% | 阶段内:daiminkan:precision |  |

机会／标签加权 run 的训练 loss 是各 batch 归一化加权损失的样本数平均，不能直接当作自然频率 NLL。完整逐轮机会指标、全部门槛与未选中检查点身份保存在配套 JSON。

### 原三麻失败诊断与唯一一次后续对照

原三麻 8 轮没有合格检查点。以最低自然验证 NLL 的第 8 轮为固定父模型，只读取固定 train／validation 中大明杠合法的窗口进行诊断；该诊断没有读取 test。下表是真实完整动作标签，不将 pass 改写为大明杠。

| 分区 | 大明杠合法窗口 | 实际正例 | TP／FP／FN | 精确正例召回 | 类型 precision | 正例平均 NLL | 大明杠对最佳其他候选平均 margin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 训练 | 78,342 | 1,765 | 132 / 77 / 1633 | 7.479% | 63.158% | 2.030601 | -1.720448 |
| 验证 | 9,769 | 224 | 11 / 22 / 213 | 4.911% | 33.333% | 2.627122 | -2.395571 |

这些观察支持检验“实际大明杠正例优化不足”的假设，不能证明原因只有这一项。两臂保留相同父模型参数、AdamW 内部步数与矩、NumPy／CPU Torch RNG；只重置阶段调度、报告和 best-state 计数。control 保持原机会加权；label2 仅把真实大明杠标签的损失额外乘 2。候选、标签、架构和原数值门槛均不改。

两臂各固定 2 个完整 epoch，学习率 0.0001、batch 2048、game-window 16。停止规则：不加第三臂、不追加 epoch 或权重网格、不做阈值后处理或候选过滤、不根据 test 再调参；没有合格候选就保留失败结果。大明杠少于 10 次预测不能建立该动作改善结论。

固定实验到此停止；本报告不把少于 10 次预测的门槛豁免描述为动作改善，也不因为整体指标提升而接受未过门槛的模型。

## 已完成的训练导出与代码检查

以下 parity 来自各完整训练 run 实际导出的最佳自然 NLL 权重，并已校验它与对应 epoch 的参数相同；它证明导出分数一致，不证明该模型通过选择或实战质量提高。

| 玩法／阶段 | 导出阶段 epoch | Torch／NumPy 样本数 | 最大分数误差 | argmax 一致 | 模型 SHA256 |
| --- | ---: | ---: | ---: | --- | --- |
| 3:original | 8 | 32 | 3.8147e-06 | True | `cdcd7f48a94a1f337e0b78555cfdc81efee562cbfa88054b997ee80c473b3274` |
| 3:control | 2 | 32 | 3.8147e-06 | True | `06ec7123b9839bf3ee181f52a6eb454676c61a473b811de833aab364eb687449` |
| 3:label2 | 2 | 32 | 3.8147e-06 | True | `019b63891381ad36c127fb7a606d7da84b36e7f2a615a8aca79be95fcc68d492` |
| 4:original | 8 | 32 | 7.62939e-06 | True | `12d07d5ea9ce99604c3c5e42ee65355e6398863d2b795f77dc95c85b18cf6a2f` |

未接受的最低 NLL 诊断锚点另完成 56 个窗口的真实权重离线兼容研究，覆盖 12 类动作、三／四麻路由、开放／关闭窗口及完整动作参数。该研究没有改变验证失败结论，也没有发布 accepted final model 或 bundle。

| 玩法 | 推理中位／P95 ms | caller 总中位／P95 ms |
| --- | ---: | ---: |
| 3 麻 | 0.395 / 0.537 | 0.483 / 0.671 |
| 4 麻 | 0.361 / 0.424 | 0.438 / 0.523 |

延迟使用合成 ActionPrototype 消息经真实状态核心、实际锚点权重和 AdviceWorker 的离线测量；包括排队、计算、取回与界面脚本生成，不包含原生 50 ms 计时器、WebKit 执行、界面显示或网络。

- policy：207 项，203 通过，4 跳过。
- worker：44 项，44 通过，0 跳过。
- node：224 项，224 通过，0 跳过。

4 个跳过是独立 clone 缺少可选既有真实牌谱 fixture：1 个 decoder public-sample smoke 与 3 个 official cached archive／probe／riichi replay；没有为补齐它们引入额外数据。回归组可能重叠，不能相加宣称独立总数。

## 续跑与保护证据

向量化迁移保留原检查点，仅改变 trainerSignature 绑定；真实批次 logits、loss、梯度、参数、AdamW 状态及 RNG／顺序逐项精确相等。2026-10-15 恢复时，先前训练进程已不存在；先保存原断点副本与 SHA，再沿原配置续跑。这是两个不同的续跑事件。

| 玩法 | 已完成 epoch | 下一轮已处理场数 | 保存优化步数 |
| --- | ---: | ---: | ---: |
| 3 麻 | 6 | 16000 | 45353 |
| 4 麻 | 3 | 28000 | 47414 |

保护记录核验时间 2026-10-15T11:31:22.396609+00:00，共 15 项通过，绑定旧记录：原输入、主仓库与旧训练 clone、已安装模型资源及签名得到核对。未宣称完整 App 每个字节与初始快照相同。

## 其他已完成实验与限制

Pilot 只用固定 train 2,048 场与 validation 512 场。全部整体、precision／机会与稀有增益 gate、数值中心化负面结果、低学习率完成及中断结果、向量化性能探针均保存在配套 JSON；未把单个稀有动作改善描述为全部 gate 通过。

三麻公开语料来自天凤，跨平台到雀魂的质量未获证明。两种玩法仍裁除杠后小局后续窗口，三麻仍裁除潜在抢北后续窗口；竞争响应没有补造 pass 标签。本轮没有修复这些覆盖边界。

没有开展在线对局、原生 GUI／WebKit／网络验收、长时后台或锁屏测试。当前结果不证明收敛、收益、胜率、棋力或所有稀有动作提升。

## 证据身份

| 证据 | SHA256 |
| --- | --- |
| [facts](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/final-report-facts.md) | `8afd70168b15672a1b6b8b15391dc605d6212fba0e345b53458e565cddcc2dbb` |
| [verificationFixture](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/tests/fixtures/policy_verify_windows.json) | `c15e52f81742acf4b5937f080828d97aed721f5b3a0bde9d5faa5d38b1456e8d` |
| [threePlayerPlan](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/three-player-full-plan.json) | `8056b0f7d8489d19eda0b00ebf8b4ea10546a62286540741364f91ba374a984c` |
| [fourPlayerPlan](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/four-player-full-plan.json) | `f73cdd13ac67b2b373f8e2c39570dab8c2bbea63b29cabe92cc84788261032b7` |
| [selectionPolicy](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/checkpoint-selection-policy.json) | `3ff51c6ff4e2a13cf8898cd59c947977c816bacf8f31ba3ea38284ef89b8bcf6` |
| [freshCache](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/fresh-cache-report.json) | `9d393af2e5a68d4e33f31a53893aeba795fb4af5e38f84413dabbed1b998512b` |
| [freshCacheIndex](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/fresh-cache-index.jsonl) | `dcb4aa2cbc97c51fa44854969461f27ff5aca61a76a21835445eeda37fdfc350` |
| [cacheIndexBinding](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/cache-consistency-final-index.json) | `4baa7b046d636f455d24121234ba8754e3044de706003695a6c4182491e48018` |
| [cache3p](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/cache-consistency-3p.json) | `a6c41b2a5879de06022a428ac3771428bcad70dc954cff1eb18b5c99ebe81849` |
| [cache4p](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/cache-consistency-4p.json) | `1e47437343b494066d3666c39d14f51717efc340f3370b77da8522282c185758` |
| [activeTrainingBinding](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/active-full-training-binding.json) | `2ba4eeaafb798706602a3861a8903cfaed8a39f9cc19438f7ecba9f2cc9418f1` |
| [resumeMigration](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-resume-migration.json) | `09a7e558e4cb9c80af4651685f8cc8704b4d672d94441e0e6be13c575bd95a2a` |
| [resumeProof](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-resume-proof.json) | `c330f0c1e0b7dd78bc7bbf09a73426b0a3a75e93894d846fd5e03af95b991705` |
| [trainingSource](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/training-source-identity.json) | `0f399fe7499ff8852251e609191703ff432361244393ac186f10ae64873e4697` |
| [vectorizedPerformance](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-weight-performance/summary.json) | `2b327beae1b828ea41eab3bec7789945403276e17db00b37f31f0e377d52e5dc` |
| [vectorizedParity](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-weight-performance/parity.json) | `c53b0bf0185f16fbfc3ba06fa2ae91781f62515612f5c3ec825c04cb65f0175d` |
| [pilotGates](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/pilot-gate-audit.json) | `2f7e7f3efd355862ba11b9bfc7d72842175d9b5b96efe0beb3384783f1a84f0a` |
| [centering](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/centering-probe-comparison.json) | `db067e907c54d42ff2d482f79930bc3644e8482db934117a59732315ea632b5e` |
| [stability](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/stability-execution-outcome.json) | `d30c8d11d19183765bf4e99797decf930abc113086635230200413e25a45b665` |
| [inputProtection](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/preserved-inputs-current-verification.json) | `ba9517bdc11f9d25b1babb2d785216ba38a14487987f11776700946f62eba754` |
| [interruptionResume](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/resume-20261015/record.json) | `0f2373da6fe188bffbf5a04c8a723d1017d5ac6165738187a864355057160e67` |
| [inputProtection20261015](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/preserved-inputs-verification-20261015.json) | `1dee2b661908f940df69a3eeaf22b4fbd9fec69b33c7bb0159d97bd69404881b` |
| [artifactManifest](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/expected-artifacts.json) | `ae02e57bfc6ae289c7ef1e84648028f484940e3534b488b8a717761548a90ea1` |
| [followupPlan](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/three-player-followup-plan.json) | `08972c847eb33ef1f8ab4da07e464279cede3391e3e8408faaa8eed7a41d28a3` |
| [followupInitialization](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/initialization-proof.json) | `869af5ffa5cbf4d4bd080dce25df6798d38f683b0eb1a896da9069bc64fea0ea` |
| [parentDiagnostic](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/conditional-daiminkan-3p.json) | `af8386b75974e828091cfef9a139a96319d7bc1aaf1ce875664d386747577622` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-8.npz](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-8.npz) | `55b41a84ace33a4ad3def122ad9e20266ae900e063d494e70be41e978a0901b1` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.report.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.report.json) | `3f2ddc30c8d59385a026ccbd5768ff99ca4e4818440d05a7bc69ebd7c790a35d` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/checkpoint-selection-policy.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/checkpoint-selection-policy.json) | `3ff51c6ff4e2a13cf8898cd59c947977c816bacf8f31ba3ea38284ef89b8bcf6` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/active-full-training-binding.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/active-full-training-binding.json) | `2ba4eeaafb798706602a3861a8903cfaed8a39f9cc19438f7ecba9f2cc9418f1` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013/.local/high-rank-50k/three-player-full/training/manifest.jsonl](/Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013/.local/high-rank-50k/three-player-full/training/manifest.jsonl) | `3d25dd7e75ddf2c02573a50d7c851d6cfbe626a5ed06973e7f021f6935bb86a7` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013/.local/high-rank-50k/three-player-full/split.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013/.local/high-rank-50k/three-player-full/split.json) | `8b555a88b2b22c2c10e15a18e0b85a459eb62c9976a1167b3ddab3dcca0a8b38` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/fresh-cache-report.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/fresh-cache-report.json) | `9d393af2e5a68d4e33f31a53893aeba795fb4af5e38f84413dabbed1b998512b` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/fresh-cache-index.jsonl](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/fresh-cache-index.jsonl) | `dcb4aa2cbc97c51fa44854969461f27ff5aca61a76a21835445eeda37fdfc350` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/conditional_daiminkan_diagnostic.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/conditional_daiminkan_diagnostic.py) | `34238f163614320a1a67cdc8ecd377a30e7656a2e7eae69b9c3a7fe6d094bb45` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_actions.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_actions.py) | `4ce54592dca8ef35459f23b6733566abb5bec6fdc86718e355ecb15094556052` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_features.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_features.py) | `86537a62645bce835caaa3ce2f5636c75f2bfaef770cbcd0bf230ff29dccd9c8` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_model.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_model.py) | `c36c96e06c88bd3f87306b20a51474e71ddc7a4c9daf4580727170559deccbe4` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_training.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_training.py) | `7438965893f4d41a46b5690d891e576d7d203c9fcf5d1eb22412b57df0fe5a4e` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_corpus_training.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_corpus_training.py) | `b27cc097bbac7dde4fdcf1c306a80eb9c6c1c9037c64412852ae1263fadc79f5` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_encoded_cache.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_encoded_cache.py) | `44babbd91dd903f4e0f299b8fcba21231074e7602f78397c97db40f838b93229` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_split.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_split.py) | `cfa5b460ba4fd3ef7617e25bd44dfedf7e48a26f1d61e0cb535cccc25aa52f9a` |
| [diagnosticBinding:/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/select_checkpoints.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/select_checkpoints.py) | `c8c28c960874bc8eb12edded5c647bb97423cf9e9aa3d2abc24adedcc138dd3b` |
| [activeBinding:three-player-full-plan.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/three-player-full-plan.json) | `8056b0f7d8489d19eda0b00ebf8b4ea10546a62286540741364f91ba374a984c` |
| [activeBinding:four-player-full-plan.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/four-player-full-plan.json) | `f73cdd13ac67b2b373f8e2c39570dab8c2bbea63b29cabe92cc84788261032b7` |
| [activeBinding:checkpoint-selection-policy.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/checkpoint-selection-policy.json) | `3ff51c6ff4e2a13cf8898cd59c947977c816bacf8f31ba3ea38284ef89b8bcf6` |
| [activeBinding:vectorized-resume-proof.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-resume-proof.json) | `c330f0c1e0b7dd78bc7bbf09a73426b0a3a75e93894d846fd5e03af95b991705` |
| [activeBinding:vectorized-resume-migration.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-resume-migration.json) | `09a7e558e4cb9c80af4651685f8cc8704b4d672d94441e0e6be13c575bd95a2a` |
| [activeBinding:training-source-identity.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/training-source-identity.json) | `0f399fe7499ff8852251e609191703ff432361244393ac186f10ae64873e4697` |
| [activeBinding:vectorized-weight-performance/summary.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/vectorized-weight-performance/summary.json) | `2b327beae1b828ea41eab3bec7789945403276e17db00b37f31f0e377d52e5dc` |
| [v1ValidationBaseline](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/v1-opportunity-baseline.json) | `d1d946254b6cd224068a96dbb9012cc1065aca3ca24fd3bf5249c20b6ded2280` |
| [3:v1Model](/Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013/.local/high-rank-50k/models/three-player-full.npz) | `c5976cd218fe1cd0cbd0bd68d76f05c426095b836eabf6ae2ddc3b674ce7cb92` |
| [3:original:report](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.report.json) | `3f2ddc30c8d59385a026ccbd5768ff99ca4e4818440d05a7bc69ebd7c790a35d` |
| [3:original:model](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.npz) | `cdcd7f48a94a1f337e0b78555cfdc81efee562cbfa88054b997ee80c473b3274` |
| [3:original:epoch-1](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-1.npz) | `434d6aef83882eb98deb6633daa34fe739be21b534a20be99864fb05cf842508` |
| [3:original:epoch-2](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-2.npz) | `607bf08e57235070805752783aad9eae30d3c11735cc5c5a3870e38347d4037b` |
| [3:original:epoch-3](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-3.npz) | `7060b739406b1a8d728254f5063e19eb2817662081b7430265395edd4c79c57f` |
| [3:original:epoch-4](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-4.npz) | `f5719b78632a1e976d18122773a3f54ef684c7869e0e5aab617af090dff705ed` |
| [3:original:epoch-5](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-5.npz) | `e0b7a6cc882249799598d5f2882fa13cd8044cadd58aec047cb55db98cdfd5b2` |
| [3:original:epoch-6](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-6.npz) | `dbcb4824f474c499f445612a1fcd10e4b241c0109593c961ac59b51068e2e333` |
| [3:original:epoch-7](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-7.npz) | `c1f6de5466285e03f3829c2f58ebb8b3eb45920c8ae9130473dd1a6aff229982` |
| [3:original:epoch-8](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/3p-opportunity.epoch-8.npz) | `55b41a84ace33a4ad3def122ad9e20266ae900e063d494e70be41e978a0901b1` |
| [3:control:report](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-control.report.json) | `2ee84aa0665f010f8b8bf6f3e240f2d64ddf9af63b94b2b2f70e7e5891552262` |
| [3:control:model](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-control.npz) | `06ec7123b9839bf3ee181f52a6eb454676c61a473b811de833aab364eb687449` |
| [3:control:epoch-1](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-control.epoch-1.npz) | `3270d7db3f5e7ef464378592feb9f54f97bc3ebfd07182e23d4e20fa04a84b9e` |
| [3:control:epoch-2](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-control.epoch-2.npz) | `62054aff217f4d47ca928dcc16f8574ecc512e79799c93fce52b6b57324b2678` |
| [3:label2:report](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-label2.report.json) | `466b24c818379d2056fdd2ed957aada5d86f320d3560d785df63ba0ce76b0353` |
| [3:label2:model](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-label2.npz) | `019b63891381ad36c127fb7a606d7da84b36e7f2a615a8aca79be95fcc68d492` |
| [3:label2:epoch-1](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-label2.epoch-1.npz) | `e268032c55149d4d86526d016936617944db2de5d1cbdb7e261eff852dec300b` |
| [3:label2:epoch-2](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/followup/3p-label2.epoch-2.npz) | `7a5781ca08216ebe8c1470031ed918e133af6bcf00f5620004590c410509bf94` |
| [4:v1Model](/Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013/.local/high-rank-50k/models/four-player-full.npz) | `4795279dfd1357294d1f49cbd307ce69400a53b1ea2c48804e8403c2e9733303` |
| [4:original:report](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.report.json) | `9e245b31d8d3d756d22450eb4181c3ba1498972bcf4012e5fdd124fedbfad411` |
| [4:original:model](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.npz) | `12d07d5ea9ce99604c3c5e42ee65355e6398863d2b795f77dc95c85b18cf6a2f` |
| [4:original:epoch-1](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-1.npz) | `d7f07b180e3c3787fe43732ef57e83d89080a471e32a2598357ffe5f298e53ba` |
| [4:original:epoch-2](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-2.npz) | `e5d41518a8e893391b1047256f291f4823878c986088dc45d7a1054d003bb7c5` |
| [4:original:epoch-3](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-3.npz) | `a36641aaf995bde21b83a1871acdec16c4cef0656e596aceefb10c6bf4228008` |
| [4:original:epoch-4](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-4.npz) | `b976e642d33d4715ae832032c2750fe284c1615026e11d4dc049b185ac1fa188` |
| [4:original:epoch-5](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-5.npz) | `60ed56ec911df339f59f120753157c55ee87d21c8c57b2e75e70798531ecb483` |
| [4:original:epoch-6](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-6.npz) | `8b437c6b250bc7d24d6a88068907f8bac789239ffff9609eb2e89b7ebfe3ea91` |
| [4:original:epoch-7](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-7.npz) | `54aa3aefe95ad13d76e0dc53dadc88a919645fdd6922f59b7926028cbd0c3643` |
| [4:original:epoch-8](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/full-vectorized/4p-constant.epoch-8.npz) | `144dd87da5385e715f3bfd209c4b53f0480b672e6dff4171ae894198a36c10d7` |
| [regression:policy](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/policy-regression-vectorized.log) | `8a05ffb840c9ea0c0a97aed9d9fd8a0b213b816d7b7e5f9a581465ec57cf9571` |
| [regression:worker](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/worker-recovery-regression.log) | `11d5f4b5077083c3d4da0f718ccb04c8ad2d0522e61aca610d26899886fb5c7a` |
| [regression:node](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/action-protocol-regression.log) | `a441a51df8fbd95817ed932919039ff254b5209f08f5cf94505451083706e0a1` |
| [source:build_validation_outcome.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/build_validation_outcome.py) | `2625739cff4f56140302ca84ce2f3e0cee5cae3a230fe470ed535ec97aa7b5bb` |
| [source:build_improvement_report.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/build_improvement_report.py) | `a3032d6fb83f9ec60b0065b0567feba756aa087c82e007e908f7c483bb133fde` |
| [source:select_followup_checkpoints.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/select_followup_checkpoints.py) | `2ce3e15238cd5eea920c027a82cee6953adab51877e5110e711ac9925397748a` |
| [source:select_checkpoints.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/select_checkpoints.py) | `c8c28c960874bc8eb12edded5c647bb97423cf9e9aa3d2abc24adedcc138dd3b` |
| [researchVerification](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/research-policy-verification.json) | `6021740d9470c7e072a861080cfcf209221b3b3f47476ef4478a25d439f0623d` |
| [researchBenchmark](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/research-live-benchmark.json) | `96ff56ba7eecdb32e8f9bade2667848c5d1201de8b238801f72c4c985f4d69cd` |
| [runtimeSource:src/policy_actions.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_actions.py) | `4ce54592dca8ef35459f23b6733566abb5bec6fdc86718e355ecb15094556052` |
| [runtimeSource:src/policy_features.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_features.py) | `86537a62645bce835caaa3ce2f5636c75f2bfaef770cbcd0bf230ff29dccd9c8` |
| [runtimeSource:src/policy_training.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_training.py) | `7438965893f4d41a46b5690d891e576d7d203c9fcf5d1eb22412b57df0fe5a4e` |
| [runtimeSource:src/policy_corpus_training.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_corpus_training.py) | `b27cc097bbac7dde4fdcf1c306a80eb9c6c1c9037c64412852ae1263fadc79f5` |
| [runtimeSource:src/policy_encoded_cache.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_encoded_cache.py) | `44babbd91dd903f4e0f299b8fcba21231074e7602f78397c97db40f838b93229` |
| [runtimeSource:src/policy_split.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_split.py) | `cfa5b460ba4fd3ef7617e25bd44dfedf7e48a26f1d61e0cb535cccc25aa52f9a` |
| [runtimeSource:src/policy_model.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_model.py) | `c36c96e06c88bd3f87306b20a51474e71ddc7a4c9daf4580727170559deccbe4` |
| [runtimeSource:src/policy_bundle.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_bundle.py) | `e3d792bc349966f6c1d71b3355d7f402d27f771b091a6b03ed1e43402d9b0716` |
| [runtimeSource:scripts/policy_prepare_bundle.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/scripts/policy_prepare_bundle.py) | `3ce861f0b4848dba81e665f7b851d5bb4e9edb01b6baefc4f9c739dbb9da4d33` |
| [runtimeSource:.local/improvement/research/final_evaluate.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/final_evaluate.py) | `d7dc7e1aa6023f2412c953ca610a8c998597a8a7e871d493f57997678fdb5109` |
| [runtimeSource:.local/improvement/research/select_checkpoints.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/select_checkpoints.py) | `c8c28c960874bc8eb12edded5c647bb97423cf9e9aa3d2abc24adedcc138dd3b` |
| [runtimeSource:.local/improvement/research/select_followup_checkpoints.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/select_followup_checkpoints.py) | `2ce3e15238cd5eea920c027a82cee6953adab51877e5110e711ac9925397748a` |
| [runtimeSource:.local/improvement/research/run_three_player_followup.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/run_three_player_followup.py) | `9c0adece3bcb5ed0a2f7621fbd0931f6f472ff56406c93570742e75040f49abe` |
| [runtimeSource:src/policy_verify.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/policy_verify.py) | `fa7945ea2b033bb3d331350315b5aa331e684f221408ffc105d5d82875c20542` |
| [runtimeSource:src/advice_worker.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/advice_worker.py) | `c69487e25d31cde213c8e60c339bbab19441a8ad002c159b72919fcf4461247d` |
| [runtimeSource:src/monitor.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/monitor.py) | `1d14e84fbcdcb161f824e195f95d131a168da38b595b3854a9679f421fd52288` |
| [runtimeSource:src/core.cjs](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/core.cjs) | `de17c642e6bfc07452f5ea988b21a11bc4dea9d3f6a9a6631cd9a5632f48a89a` |
| [runtimeSource:src/unity_transport.js](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/unity_transport.js) | `ef8ba48c96243e93e59fc1a39746dabfb94b01fcc965ffad8b0d87ce44f87b96` |
| [runtimeSource:src/browser.js](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/src/browser.js) | `f15d9e1e4a02473588b2f112890fc63124ca8cab35f1d12d1ec499fd873691a0` |
| [runtimeSource:scripts/policy_live_benchmark.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/scripts/policy_live_benchmark.py) | `1f73a68bd2a8193992a2ebb7b9a98da9ed3b8c824c59bb2ed7bfa9a98e0335fa` |
| [runtimeSource:tests/test_policy_live_windows.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/tests/test_policy_live_windows.py) | `e719bb6810c0905969cbbaee442e9331a3483c8811a2796230e7847e486d99b7` |
| [runtimeSource:tests/helpers/policy_live_windows.cjs](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/tests/helpers/policy_live_windows.cjs) | `f4359706f09d8bffe079c482f156389a5bb44d5aa73f379e74880aacaf47636d` |
| [runtimeSource:.local/improvement/research/run_final_acceptance.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/run_final_acceptance.py) | `5927f082e581ced94f94b16336d5b34b0ef13c34c86af08e0877752bd54c6db5` |
| [runtimeSource:.local/improvement/research/run_research_acceptance.py](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/research/run_research_acceptance.py) | `9ae6c559c2f576484f40afb2c283ce6483a918347d009eaf6f237df11d3b592c` |
