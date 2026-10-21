# 已按用户要求暂停

PID40946已通过STOP退出；诊断未完成。恢复前先读[暂停交接](pause-handoff.md)和pause-handoff.json，不移除STOP或覆盖output重跑。以下保留启动记录。

# 四麻完整fit诊断：后续入口

当前阶段：已冻结并于2026-10-20 10:47:04 UTC启动，PID40946，日志`run.log`，启动凭据`launch.json`。计划SHA `73ebe8a561cf0e509f15b5f2a746e9848e55c325c068ab7db2252912714d492d`。13项合成测试通过，独立范围与统计审查无阻断。真实活动状态在`output/state.json`，不是本目录顶层；以该状态、真实PID和日志为准，禁止重复启动或覆盖。

实现SHA `89f3a980193f3d287ae2019084381c074f2ba887d5baa7c1708ca56b1eb0b33c`，测试SHA `5b10ee543113a302eb59d4d99c4a62a7818e4a36b1a388b270cff7dfc4f2470e`。源码、计划及判断规则已经冻结，不得热修。完成必须同时有`output/summary.json`、绑定摘要的`output/completion.json`及`output/state.json`的completed，之后独立复核；任何单独进度行不算完成。

上一轮四臂训练与评估已经完整结束，见相邻`all-actions-75-four-player-objective-20261020/README.md`。结果是质量拒绝；旧链禁止重启、热修、追加轮数或择优选checkpoint。

本轮仅执行`diagnostic-design.md`定义的固定4,096局fit、四固定终点曝光与吃/大明杠分数包络检查，0训练更新、0新模型写入、0holdout载荷、0validation/test/raw/source载荷。不改旧代码或旧状态，不部署推送合并。

预算固定为1200秒、RSS4GiB、MPS driver2GiB、CPU1；每局共享一次解码，结束另做4096次缓存字节SHA复核，因此字节读取计数8192、解码4096。失败先保存现场，不自动重跑、覆盖或扩预算。机械完成、训练侧机制证据、研究质量和用户全动作严格75%目标分别报告。
