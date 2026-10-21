> 2026-10-18 16:38 最新：tilelocal四组训练、8192局共同评估与独立分析全部完成，state终态completed；完整质量筛查与机制筛查均未通过。两个混合目标实际模型立直完整Top1为75.680%/75.488%，各自仍缺弃牌67.626%/67.827%和大明杠63.341%/51.508%，误选保护亦失败。新入口为 ../all-actions-75-structural-20261018/README.md：公开向听数/结构有效未见张数的fit与新holdout预计算已启动，尚未冻结训练plan或启动真实训练。请核对新目录两份preparation计划、launch凭据、log和真实进程，不能重启任何旧completed/failed流程。原四麻原8轮训练已完成，原独立验收继续。以下保留历史记录。

> 2026-10-18 16:02 最新：bilinear四组固定训练、8192局共同评估与筛查均已完成；各实际模型仍未全部适用动作严格>75%，完整质量筛查 rejected-full-quality-screen。逐动作变化见 all-actions-75-bilinear-20261018/bilinear-result-analysis.md。现已冻结并启动独立 all-actions-75-tilelocal-20261018 四组对照，只给弃牌/立直增加128个牌位置读取参数；最新入口为该目录README.md/state.json，计划 SHA `daa203e1ccdda7f52ae1b730ef3c215e9e9820e85b04942bb12576436f8ac21e`。排除此前20480局后使用新8192局留出；旧四麻8轮训练已完成，正在独立验收。原automation条目已不存在，独立进程会自行完成本轮。以下均为保留历史记录。

# 当前活动：直接状态—完整候选交互四臂对照

最新入口为本目录。唯一活动状态是 state.json，启动记录 launch-receipt.json。计划 SHA256：75c7c2ee6627a43ce90798a8faa11d0fdf5569ff74a4bc7031ce6350ee893402。

前轮 all-actions-75-stable-20261018 已完成4组5000步、完整8192局留出评估和最终筛查，结论 rejected-screen；每个模型均未全部适用动作>75%。分析见该目录pilot-result-analysis.md/json、decision.json及gating-audit-report-20261018.md。更旧 all-actions-75-20261018 第一臂为数值失效，不得恢复或作为目标对照质量结论。

本轮4个bilinear模型按 seed42-natural、seed42-mix、seed43-mix、seed43-natural 顺序从同主干随机初始化训练，固定5000更新，全部fit数据、抽样序列、两种目标与优化预算复用。评分头使用hᵀWa+bᵀa，保留134维完整候选，参数更少。四个已完成stable终点作为对照，不重复训练。两个目标都保留以区分结构改变与稀有动作目标取舍；不是批准前轮混合目标。

新8192局自然holdout从原train中排除前轮4096fit+8192holdout后预先哈希选出，old4098/new4094；2581110个choice窗口。数据资格验证passed，完整统计与准备报告精确一致。对这8个4096fit模型未见，不能称历史全train模型也未见。256fitMonitor仍仅诊断。禁止正式validation/test载荷、raw/source样本读取。

执行链：run_pilot.py → 四次train_bilinear.py → evaluate_bilinear.py对同一新holdout评估8模型 → analyze_bilinear.py输出decision.json/md。中间checkpoint不做holdout择优。每组自然或mix与对应control逐样本序列相同，终点强制校验hash和exposure。source、输入、模型、初始化、计划均绑定。先核实真实进程/输出，不重复启动或覆盖。

判断分开：结构机制信号、原质量screen全部门槛、用户每模型全部适用动作完整Top1严格>75%；不得拼接最佳seed/action，不用类型/条件准确率代替。previousDecision绑定旧rejected结果。完整质量即使通过也不授权App部署。本轮研究导出不兼容已安装评分器。

并行原四麻链继续：../action-causes-20261016/recovery-20261018-0415/state.json 与resume-training.log是唯一恢复实况；8轮原预算结束后完整独立验收。旧running/waiting为中断历史不可重启。原核心、冻结计划和活动脚本不改，主仓库/App/原始语料不变，不部署推送合并。

故障先保存现场、日志、checkpoint及hash核对再恢复，不能更改已冻结预算/门槛直至通过。新模型仅在当前公开可见状态与完整真实动作上做监督模仿，禁隐藏/未来/手数/赛程特征及奖励/RL。继续自动跟进直到实际目标和必要验收完成，未达成不得暂停自动跟进或归档聊天。

自动跟进备注：本轮尝试更新 automation 条目时，工具返回该条目在App中不存在；未创建替代条目。当前独立run_pilot进程仍会自动跑完四组训练、共同评估与汇总，但不能据此声称后续聊天自动唤醒已经配置成功。详情见continuation-receipt-20261018.json。
