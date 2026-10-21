# 三麻立直机会窗口对照实验

验收结果：**rejected**。主结果固定为第 3 轮；没有事后选择最优轮次。

实验模型仅用于研究。已安装 App 未修改，测试集未读取；本报告不授权部署或自动全量重训。

两组的机会权重审计都统计“实验规则相对对照规则可能影响的窗口”；其中的变化窗口数并不表示对照组实际加权，对照组始终保留原有权重。

冻结计划：`8df5fcc85569e6bb3bb6686c772f58bd532e6701e679cf16db023b48e910253b`。执行设备：cpu，2 个计算线程。

| 模型／轮次 | 自然验证 NLL | 总体 Top1 | 立直类型召回 | 立直完整动作召回 | 立直精确率 | 立直 FPR |
|---|---:|---:|---:|---:|---:|---:|
| v1 | 0.670240 | 75.442% | 71.604% | 64.368% | 66.186% | 15.608% |
| parent | 0.642425 | 76.275% | 73.989% | 67.416% | 66.917% | 15.607% |
| control / 1 | 0.642426 | 76.269% | 70.074% | 63.748% | 69.188% | 13.315% |
| control / 2 | 0.643410 | 76.237% | 72.998% | 66.412% | 67.631% | 14.907% |
| control / 3 | 0.643845 | 76.190% | 72.835% | 66.145% | 67.678% | 14.841% |
| riichi2 / 1 | 0.642634 | 76.258% | 68.473% | 62.387% | 70.167% | 12.421% |
| riichi2 / 2 | 0.643608 | 76.233% | 72.928% | 66.309% | 67.828% | 14.759% |
| riichi2 / 3 | 0.644089 | 76.174% | 73.679% | 66.896% | 67.173% | 15.362% |

v1 在 100,270 个固定公开立直机会窗口中预测立直 32,442 次（32.355%），牌谱真实立直 29,987 次（29.906%）。这是这些固定机会窗口中的选择频率，不是连续实战立直率；需要同时约束漏选与误选，不能只追求增加立直次数。

初始 v2 相对 v1 已存在以下完整动作准确率下降：abort -0.762 个百分点、shouminkan -6.168 个百分点。这些差异在本次处理前就存在；对 v1 的门槛失败不能自动归因于立直加权，处理效应需要看实验组与匹配对照组的差值。

下表只统计牌谱实际选择立直的窗口，区分类型判断与完整参数。计数表示与记录选择的一致程度，不判定哪种打法最优；两组实验均使用第 3 轮。

| 模型 | 真实立直 | 改选普通出牌 | 改选其他动作 | 选立直但参数不一致 | 完整动作一致 |
|---|---:|---:|---|---:|---:|
| v1 | 29987 | 8407 | ankan: 32、kita: 55、tsumo: 21 | 2170 | 19302 |
| parent | 29987 | 7709 | ankan: 32、kita: 38、tsumo: 21 | 1971 | 20216 |
| control | 29987 | 8046 | ankan: 37、kita: 42、tsumo: 21 | 2006 | 19835 |
| riichi2 | 29987 | 7791 | ankan: 40、kita: 41、tsumo: 21 | 2034 | 20060 |

参数不一致总数按窗口计一次。配套 JSON 中弃牌、红牌、摸切等字段可能重叠，不能把这些字段计数直接相加。

同一张牌、同一红牌身份、同一摸切参数下，立直分数减普通出牌分数的平均值如下。正值表示该候选对中更偏好立直；这不是和牌率或胜率，跨模型还需结合动作指标解读。

| 模型 | 真实立直候选对：均值／数量 | 真实普通出牌候选对：均值／数量 |
|---|---:|---:|
| v1 | +0.744518 / 29987 | -2.133297 / 56644 |
| parent | +0.931366 / 29987 | -2.144233 / 56644 |
| control | +0.879804 / 29987 | -2.212903 / 56644 |
| riichi2 | +0.931656 / 29987 | -2.181872 / 56644 |

冻结验收规则如下，直接来自本次验收记录。数值为比例或 NLL 的原始单位；最低分母要求同时适用于实验组和参照组。全部保护条件须满足，改善条件按冻结的 all 规则组合。

| 类别 | 指标 | 参照 | 门槛 | 最低分母 |
|---|---|---|---|---:|
| 保护 | `choiceNll` | v1/parent/control | ≤ 参照值 + 0.005 | 100000 |
| 保护 | `choiceTop1` | v1/parent/control | ≥ 参照值 − 0.002 | 100000 |
| 保护 | `byAction.discard.accuracy` | v1/parent/control | ≥ 参照值 − 0.002 | 100000 |
| 保护 | `byOpportunity.riichi.recall` | v1/parent/control | ≥ 参照值 − 0.003 | 1000 |
| 保护 | `byOpportunity.riichi.exactPositiveRecall` | v1/parent/control | ≥ 参照值 − 0.003 | 1000 |
| 保护 | `byOpportunity.riichi.precision` | v1/parent/control | ≥ 参照值 − 0.01 | 1000 |
| 保护 | `byOpportunity.riichi.falsePositiveRate` | v1/parent/control | ≤ 参照值 + 0.005 | 1000 |
| 保护 | `byOpportunity.riichi.exactCandidateTop1` | v1/parent/control | ≥ 参照值 − 0.003 | 1000 |
| 保护 | `byAction.pon.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.ankan.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.shouminkan.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.kita.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.pass.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.tsumo.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.ron.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byAction.abort.accuracy` | v1/parent/control | ≥ 参照值 − 0.003 | 100 |
| 保护 | `byOpportunity.daiminkan.precision` | parent/control | ≥ 参照值 − 0.05 | 20 |
| 保护 | `byOpportunity.daiminkan.recall` | parent/control | ≥ 参照值 − 0.01 | 100 |
| 保护 | `byOpportunity.daiminkan.falsePositiveRate` | parent/control | ≤ 参照值 + 0.001 | 1000 |
| 保护 | `byOpportunity.daiminkan.exactCandidateTop1` | v1/parent/control | ≥ 参照值 − 0.003 | 1000 |
| 保护 | `byOpportunity.daiminkan.passAvailableExactCandidateTop1` | control 的 byOpportunity.daiminkan.alwaysPassTop1 | ≥ 参照值 − 0 | 1000 |
| 改善 | `byOpportunity.riichi.recall` | control | ≥ 参照值 + 0.005 | 1000 |
| 改善 | `byOpportunity.riichi.exactPositiveRecall` | control | ≥ 参照值 + 0.005 | 1000 |

以下逐项列出未通过或证据不足的条件；全部精确值、差值和分母见 JSON：

- `byOpportunity.riichi.recall` 对比 `parent`：failed；差值 -0.003101；分母 29987 / 29987。
- `byOpportunity.riichi.exactPositiveRecall` 对比 `parent`：failed；差值 -0.005202；分母 29987 / 29987。
- `byOpportunity.riichi.falsePositiveRate` 对比 `control`：failed；差值 +0.005208；分母 70283 / 70283。
- `byAction.shouminkan.accuracy` 对比 `v1`：failed；差值 -0.034121；分母 1524 / 1524。
- `byAction.pass.accuracy` 对比 `v1`：failed；差值 -0.005828；分母 100376 / 100376。
- `byAction.pass.accuracy` 对比 `parent`：failed；差值 -0.003736；分母 100376 / 100376。
- `byAction.abort.accuracy` 对比 `v1`：failed；差值 -0.003049；分母 1312 / 1312。
- `byOpportunity.daiminkan.recall` 对比 `parent`：failed；差值 -0.017857；分母 224 / 224。

大明杠的自然验证结果如下；可跳过子集上的模型与始终跳过基线使用相同分母。

| 模型 | TP / FP / FN | 精确率 | 召回率 | 可跳过子集模型准确率 | 同子集始终跳过 |
|---|---:|---:|---:|---:|---:|
| v1 | 1 / 1 / 223 | 50.000% | 0.446% | 93.776% | 92.794% |
| parent | 11 / 22 / 213 | 33.333% | 4.911% | 94.298% | 92.794% |
| control | 8 / 16 / 216 | 33.333% | 3.571% | 94.268% | 92.794% |
| riichi2 | 7 / 17 / 217 | 29.167% | 3.125% | 94.298% | 92.794% |

收敛诊断只比较固定自然训练监测集和固定验证集；训练中的加权在线损失不与自然验证损失直接比较。

- control / trainMonitor：not_plateau；自然 NLL 为 0.625250 → 0.618361 → 0.614405 → 0.610280；大明杠正例支持状态 insufficient_evidence。
  该固定监测集各检查点只有 23 / 23 / 23 / 23 个大明杠正例，低于预先要求的 100 个，不能据此判断大明杠已收敛。
- control / validation：not_plateau；自然 NLL 为 0.642425 → 0.642426 → 0.643410 → 0.643845；大明杠正例支持状态 support_sufficient_for_description。
- riichi2 / trainMonitor：not_plateau；自然 NLL 为 0.625250 → 0.618483 → 0.614510 → 0.610548；大明杠正例支持状态 insufficient_evidence。
  该固定监测集各检查点只有 23 / 23 / 23 / 23 个大明杠正例，低于预先要求的 100 个，不能据此判断大明杠已收敛。
- riichi2 / validation：not_plateau；自然 NLL 为 0.642425 → 0.642634 → 0.643608 → 0.644089；大明杠正例支持状态 support_sufficient_for_description。

平台期判定采用冻结计划中的最后两个连续区间和立直召回波动限制。三轮小规模继续训练不足以证明整体训练已收敛。

实验边界：两组只使用单一父模型及随机状态、固定训练划分的前 2,048 场，没有跨种子或子集重复；4,706 场验证集已在此前研究中被反复查看。512 场自然监测集属于本次训练子集，作用是固定口径观察拟合；同一牌局内的窗口不是相互独立的样本。本次结果仅用于判断是否值得制定完整训练方案，不是独立泛化证明或部署验收。

上述准确率衡量与公开牌谱真实选择的一致程度，不代表最优打法或实战强度。分动作混淆、参数错误、正负例 NLL、同牌立直分差、数值范围及每轮模型哈希均保存在配套 JSON 中。

MPS 在读取语料及真实训练前的设备预检阶段不可用，因此预先修订为 CPU。设备速度测试使用合成输入，不属于模型训练或选模。

CPU 重算的 v1 与历史基线并非计数完全相同：普通出牌完整动作正确数变化 +1，自然 NLL 差值 +7.285e-09。本实验统一使用此次 CPU 基线；聚合统计不能确定所有逐条预测是否相同，也不能单凭它确定差异原因。

补充审计证据及文件哈希：

- [v1-cpu-equivalence.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/v1-cpu-equivalence.json)：`00cd35acb6dfa6650197a76d585a1116ed61c5417b2caa869d9bbb252b93570b`。
- [parent-cpu-equivalence.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/parent-cpu-equivalence.json)：`692e1a3b3a207a604a744f395ed8b0350af7f6db2517c3d85dd57d78507dd7fd`。
- [convergence-kan-audit.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/convergence-kan-audit.json)：`44f0e052e7053121127754087fea9dddffb69878de5cc8847d89f0b111bd6f3a`。
- [preparation-checks.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/preparation-checks.json)：`f6909eea120fe3ae10d4bb32bfde9e0a29a75fd31ca72606750db520f93be371`。
- [riichi-objective-audit.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/riichi-objective-audit.json)：`b56510937f2690e5325059cebe5ef3cdf85527664fc06f9df1b500f9096ba211`。
- [daiminkan-path-audit.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/daiminkan-path-audit.json)：`d9e1e8dd0c24acaf6b66eb442ace4ff11c0e3cf14af98e1c96c45c59d349a291`。
- [control-completion-audit.json](/Users/kenny/Desktop/Maj-Soul-PlusPlus-improvement-20261013/.local/improvement/riichi-20261016/control-completion-audit.json)：`de35f5428c784aeea02e387d78178bcc5ea7022be7f7eec9d85ad8cac9e6f4d8`。
