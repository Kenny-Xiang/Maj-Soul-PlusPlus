> 2026-10-20 续接：本轮所有训练、自然评估与筛查已完成，未达单模型全部动作严格>75%，不要重启。当前后续实现入口为 `../all-actions-75-kan-sampling-20261018/README.md`；旧四麻全量训练及验收也已完成、无合格检查点。以下保留历史记录。

> 2026-10-18 16:38 最新：tilelocal四组训练、8192局共同评估与独立分析全部完成，state终态completed；完整质量筛查与机制筛查均未通过。两个混合目标实际模型立直完整Top1为75.680%/75.488%，各自仍缺弃牌67.626%/67.827%和大明杠63.341%/51.508%，误选保护亦失败。新入口为 ../all-actions-75-structural-20261018/README.md：公开向听数/结构有效未见张数的fit与新holdout预计算已启动，尚未冻结训练plan或启动真实训练。请核对新目录两份preparation计划、launch凭据、log和真实进程，不能重启任何旧completed/failed流程。原四麻原8轮训练已完成，原独立验收继续。以下保留历史记录。

> 2026-10-18 16:02 最新：bilinear四组固定训练、8192局共同评估与筛查均已完成；各实际模型仍未全部适用动作严格>75%，完整质量筛查 rejected-full-quality-screen。逐动作变化见 all-actions-75-bilinear-20261018/bilinear-result-analysis.md。现已冻结并启动独立 all-actions-75-tilelocal-20261018 四组对照，只给弃牌/立直增加128个牌位置读取参数；最新入口为该目录README.md/state.json，计划 SHA `daa203e1ccdda7f52ae1b730ef3c215e9e9820e85b04942bb12576436f8ac21e`。排除此前20480局后使用新8192局留出；旧四麻8轮训练已完成，正在独立验收。原automation条目已不存在，独立进程会自行完成本轮。以下均为保留历史记录。

> 2026-10-18 13:25 最新：stable 四臂训练、完整留出评估、筛查均已完成；结论 rejected-screen，四模型均未全部适用动作严格>75%。完整逐动作变化及误报见 all-actions-75-stable-20261018/pilot-result-analysis.md。基于终点评估与 train-only 门控审计，已启动独立 all-actions-75-bilinear-20261018 四组固定5000步新结构对照；最新入口为该目录README.md/state.json。计划 SHA `75c7c2ee6627a43ce90798a8faa11d0fdf5569ff74a4bc7031ce6350ee893402`。新旧8模型共用新8192自然整局留出；不重复旧训练，研究完成与质量通过分别记录。以下为保留的历史记录。

# 全动作75%优化：稳定计算版

2026-10-18 12:52 Asia/Shanghai，已从头启动同条件四臂对照。当前目录是唯一活动的新优化链，`state.json`和`seed*-*.log`提供真实执行进度。冻结计划SHA256：`e6299b8514e803131b76ad6ea0d2fe99de5cdc9fdd9777fa81e096ad95fe191f`。driver PID7483。首臂完成不代表质量通过；四臂终点会统一评估并生成`decision.json/md`。

数据、动作目标、两种子、采样、5000×512更新预算与筛查规则沿用上一版；数据来自原train整局4096 fit/8192 holdout，不使用旧模型权重。新旧完整设计、baseline及数据准备见`../all-actions-75-20261018/README.md`和该目录的绑定文件。当前所有适用动作>75%的目标尚未达到。

上一版首臂数值失效，未评估holdout，已结束并保留现场。此版仅修正每候选共享公共分数的浮点计算；数学上保持softmax、CE和排序。详细证据和限制见`numerical-correction.md`。22项合成CPU/MPS测试及合成运行检查通过；真实训练每batch检查合法logit与裁剪前梯度是否达到1e6，异常就保留现场停止，不挑中途模型。

训练和评估都使用独立StableCandidatePolicy。导出仅作研究，标明稳定打分语义，不能直接替换App模型。主仓库/App/原始语料不变，旧四麻链继续，不修改旧核心、计划或验收门槛。test载荷始终关闭。仅监督当前公开状态到完整真实动作，不加隐藏/未来/当前手数/赛程特征，不用奖励/RL。

成功后查看evaluation/report.json、per-game.npz以及decision.json/md。两个种子分别判断完整目标、平均短缺、最差动作和误选保护。若失败，依据类型/参数/fit-holdout分解决定下一步独立实验；不要重启旧异常运行、改冻结计划、覆盖结果或追加到通过。恢复时核实实际进程和检查点，state文件不能单独证明活跃。旧四麻状态在../action-causes-20261016/recovery-20261018-0415/state.json。
