> 2026-10-20 用户要求暂停。后续训练侧诊断已通过STOP退出，完整交接见相邻 all-actions-75-four-player-fit-diagnostic-20261020/pause-handoff.md；禁止自动恢复。

# 四麻固定预算目标函数对照：已完成

本目录 `state.json` 已于2026-10-20 10:29:28 UTC记录 `completed`；四次训练、联合评估、配对统计六阶段全部exit0。计划 SHA：`efc3a869cfd666d2bebd25e32adb844198dc586f50791d37768319a05462a474`。不得重启、覆盖或追加预算。原执行器PID38991与评估PID39101已核实退出。

**机械完成，质量拒绝，目标未达成。** `decision.json` 为 `rejected-full-quality-screen`。两个mix实际模型各自只有discard、chi未严格超过75%，但稀有动作和立直误报、过及弃牌退步使完整保护失败。seed42/43 mix弃牌62.886%/62.822%，吃50.515%/46.519%；大明杠完整76.971%/81.917%，同时precision仅10.460%/11.007%、机会FPR21.213%/21.323%。不得把大明杠的点值视为质量通过。历史正式政策not-assessed，不部署。

`final-artifact-audit.json`通过95项身份与完成检查（SHA `460649e81cd0d2992556adb7cd18aebdfdc48a3d4e065805ebad1d5844448f81`）。四终点训练独立审查见`training-result-review-correction.json`；其原始审查的stdout逐行等式误把三行PyTorch warning计为训练失败，原失败记录完整保留，100条结构化日志、抽样、模型和预算均一致，纠正未改变实验门槛。

后续设计见`next-step-review.md`与相邻`all-actions-75-four-player-fit-diagnostic-20261020/diagnostic-design.md`：在相同4,096局fit和四个固定终点上检查曝光次数与候选排序，以及吃/大明杠的正负机会分数包络。该诊断尚须冻结和执行，以新目录状态为准；不能把本目录已完成状态当作新诊断已运行。新目录只做训练侧诊断，不读取holdout载荷，不更新模型。

2026-10-20 已完成身份准备、缓存资格、两种子 CPU/MPS 数值资格及资源预检；57 项合成回归无跳过通过、45 项支持检查全过。四麻fresh natural/mix × seeds42/43使用共同bilinear模型、同种子相同初值/完整抽样链，每臂固定5,000×512。全部四终点在同一8192局holdout及256局fitMonitor完成联合评估，评估约670秒；监测集不参与筛查或bootstrap。

- fit 4,096局，choice 2,462,763，完整候选22,618,035；old/new 2,039/2,057。
- holdout 8,192局，choice 4,939,504；old/new 4,149/4,043，整局无重叠，全部原train。
- 吃牌choice正例：fit32,640（4,063局），hold65,893（8,147局）。
- 大明杠choice正例：fit309（295局），hold647（605局），hold负机会20,096。
- 实际缓存资格读取12,288局；四臂全部训练结束后才完成8192局内部holdout模型评分。正式validation/test、原始/source样本未读。

数值检查两种子 CPU/MPS 最大logit误差2.38e-7、最大梯度误差5.96e-8，未更新真实模型。资源预检50个真实fit批次只作CPU读取，50次更新均为独立合成输入。数据产物约31.03GB，资格扫描147.58秒，预检13.91秒。

最终合成联测曾因跨suite的sys.path污染误导入旧同名资源脚本并停止，证据 `freeze-attempt-1.json`。该旧脚本仅执行50次合成更新，无真实数据或模型权重读取；原结果SHA不变。只修未冻结的测试启动器为逐suite独立进程，保留所有冻结源码/数据/门槛，最终57项通过。不能重跑旧实验。

目标仍是三麻、四麻各一个实际模型的所有适用动作choice-only完整候选Top1严格>75%，含具体立直弃牌/副露参数。四麻kita N/A，其他11类逐个判断；类型/条件指标不可替代目标。完整screen及误报保护不改，五类历史绝对precision原值另外检查；历史正式政策not-assessed。不拼接模型最佳项，不部署。

前轮三麻数据扩充、四麻吃牌诊断、三麻梯度诊断均已完成，不能重启；分别见相邻 `all-actions-75-data-diversity-20261020`、`all-actions-75-four-player-diagnostic-20261020`、`all-actions-75-gradient-diagnostic-20261020` 目录。原公共分数数值失败的首版也不能重启。主仓库/App/原始语料保持，不推送或合并。

所有失败和检查纠正证据均保留；冻结代码/计划/阈值和原状态不再修改。结果从`decision.json`/`decision.md`及终点identity核实，完成与质量通过分开报告。后续实验必须使用独立目录和新冻结计划。
