> 2026-10-20 续接：本轮所有训练、自然评估与筛查已完成，未达单模型全部动作严格>75%，不要重启。当前后续实现入口为 `../all-actions-75-kan-sampling-20261018/README.md`；旧四麻全量训练及验收也已完成、无合格检查点。以下保留历史记录。

# 当前执行阶段：公开结构特征四组对照

最新研究入口为本目录。上一轮tilelocal四组训练、完整评估和分析已经完成；其state.json是终态completed，不能重启。本轮已于2026-10-18T09:18:03Z冻结计划并实际启动，计划SHA a616465bf07b9269132657472c96c120f0532623ca1b00a1f4befa1561737a24，driver PID18678。当前唯一训练状态为本目录state.json，启动凭据launch.json；实际PID与.log共同核实，禁止重复启动或覆盖。四组各固定5000步完成后，由同一driver运行八个新旧模型的共同自然留出评估及固定判定。当前尚无本轮质量结果。

原4096局fit结构预计算已完整通过：1,286,222窗口、12,755,535候选、4096独立oracle完全一致，见fit-readiness-check.json。新8192局holdout也已完整通过：2,607,204窗口、25,840,717候选、4096独立oracle完全一致，报告SHA 95c0c4ecc8cf56acb60131e8dfc4090e87325881bd7aeb450a62fca550b73fc4。完整8192行索引与两份报告已在训练前通过现有评估器强资格检查，见launch-control/artifact-readiness.json；其绑定与最终plan精确相等。准备通过不等于模型质量通过。

单次接续已正常完成交接，见launch-control/state.json，不能重新运行。其contract SHA 2ef07ee05ca2edd2d5c636214598185a03554eec4de4e2b5ad186960eb67e6d2，入口SHA 4b7b9a84e7a5049bf31b46b785833e19ede60f3b48d4fb7a53bdf78962b99ebe，独立复核见launch-control/review.md。它只等待原PID15894，完整准备通过后核验、冻结并启动一次。两个预计算进程和接续进程均已结束；当前训练以本目录state.json为准。任一实际训练/评估失败均保留现场核查，不盲目重启。

设计见experiment-design.md。目标仍是三麻、四麻各一个实际模型的全部适用动作完整Top1严格>75%，包含立直具体弃牌。tilelocal两个混合目标模型立直75.680%/75.488%，但弃牌67.626%/67.827%、大明杠63.341%/51.508%，且误选保护失败；无模型达成全部目标。

fit准备计划SHA d17df4a1caccdaac097a344dc7e95c86d472a60199090ca806ccd1c804e366d8，holdout结构计划SHA f78c9cabefa4c77722e26c5c377e65dbfe3b8d75e6d53d067f82a731db2d7f7b。两份报告均passed并已冻结绑定；启动凭据、日志、完整产物全部保留，不能重新运行或覆盖预计算。

大明杠诊断见../all-actions-75-bilinear-20261018/kan-fit-audit-20261018/result-review.md，包含完整fit机会margin与精确采样曝光证据。结构可行性见../structural-features-review-20261018/feasibility-review.md。所有已冻结旧产物保持。

并行四麻原8轮训练已完成，正在逐模型独立验收。唯一恢复状态为../action-causes-20261016/recovery-20261018-0415/state.json；2026-10-18T09:08Z观察已完成v1、parent、epoch-1及epoch-2，正在epoch-3验收。旧running/waiting为中断历史，不可重启。旧核心、冻结计划、门槛和活动脚本不改。

主仓库/App/原始语料不变，不部署推送合并。不读test载荷、正式validation载荷或原始牌谱；本新研究只用获准的原train编码缓存/fit映射和划分元数据。仅当前公开状态到真实完整动作的监督模仿，禁止隐藏/真实未来/手数/赛程/奖励/RL。原automation条目已不存在，不能声称已恢复定时唤醒；持续目标仍在进行，不归档聊天。

统一81项CPU/MPS合成检查（0失败/0跳过）的源码集合与每项SHA已在训练前再次核对，见synthetic-qualification.json/log；训练/冻结入口与评估器均有独立审查，无阻断。当前计划已冻结，核心源码、输入、目标、固定预算与全部判断规则均保持。主线结构实验评估结束前，不启动大明杠抽样草案，不将其他实验更改混入本轮。
