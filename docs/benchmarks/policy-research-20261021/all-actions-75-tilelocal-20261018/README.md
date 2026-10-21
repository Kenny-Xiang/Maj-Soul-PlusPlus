> 2026-10-18 16:38 最新：tilelocal四组训练、8192局共同评估与独立分析全部完成，state终态completed；完整质量筛查与机制筛查均未通过。两个混合目标实际模型立直完整Top1为75.680%/75.488%，各自仍缺弃牌67.626%/67.827%和大明杠63.341%/51.508%，误选保护亦失败。新入口为 ../all-actions-75-structural-20261018/README.md：公开向听数/结构有效未见张数的fit与新holdout预计算已启动，尚未冻结训练plan或启动真实训练。请核对新目录两份preparation计划、launch凭据、log和真实进程，不能重启任何旧completed/failed流程。原四麻原8轮训练已完成，原独立验收继续。以下保留历史记录。

# 当前活动：候选牌位置直连四组对照

最新执行入口为本目录，唯一活动状态为 state.json，启动凭据为 launch-receipt.json。计划 SHA256：daa203e1ccdda7f52ae1b730ef3c215e9e9820e85b04942bb12576436f8ac21e。先核对真实进程和输出，不能重复启动或覆盖结果。

上一轮 all-actions-75-bilinear-20261018 的四组训练、8192局共同评估与筛查已完成。四个实际模型均未达到全部适用动作完整Top1严格高于75%，完整质量筛查 rejected-full-quality-screen，两个目标的机制要求均未全部满足。详见该目录 bilinear-result-analysis.md/json 与 decision.json。更早 stable 四组也已完成并拒绝；最早 all-actions-75-20261018 的首臂数值失效，不能恢复或作为目标质量结论。

本轮检验弃牌与立直的候选内排序瓶颈：在原 bilinear 模型上给这两类候选增加牌位置对应的64维卷积特征读取，仅新增2×64=128个零初始化参数，完整134维候选和原主干保留。初始分数与旧参数未裁剪梯度一致；新增梯度参加原全局裁剪，不宣称首步更新等价。研究打分语义 bilinear-discard-riichi-tilelocal-v1，导出不能直接部署App。

训练顺序 seed42-natural、seed42-mix、seed43-mix、seed43-natural，各固定5000步，batch512。原4096局fit、种子、抽样序列、自然CE/.75natural+.25macroCE、优化器与学习率预算均保持。全部从配对随机初始化开始，不热启动全量模型，不增加轮数至通过。四个已完成bilinear终点作为对照，不重复训练。

新8192局自然holdout从原train排除此前20480局fit/holdout后按冻结规则选择，old4098/new4094；2591645个choice窗口、25693890个完整候选。大明杠431正例、410正例局、16639机会负例；数据准备与独立资格核验均通过。原256局fitMonitor仅作诊断。正式validation/test、raw/source样本不得读取。

run_pilot.py 将依次执行四组训练、evaluate_tilelocal.py共同评估8个模型、analyze_tilelocal.py输出decision.json/md。中间checkpoint不能看holdout择优。数据/源码/模型/初始化/计划均绑定SHA；训练采样序列和曝光数须匹配原对照。故障先保留现场与checkpoint，核对哈希再恢复。

判断分别报告：结构机制要求、原质量screen全部门槛、用户每模型全部适用动作完整Top1严格>75%、历史正式验收。不得拼接不同模型最佳动作；立直包含弃牌参数；三麻吃为N/A。当前pilot只有三麻，不构成三麻/四麻全部完成或App提升资格。大明杠召回仍受precision与机会误报保护。

并行旧四麻链已完成原8轮训练，正在独立验收；唯一恢复入口 ../action-causes-20261016/recovery-20261018-0415/state.json，日志与该目录顶部交接说明为准。旧running/waiting为中断历史不可重启。链结束前旧核心源码、冻结计划、门槛和活动脚本不改。

主仓库/App/原始语料不变，不部署、推送或合并。仅监督模仿当前公开可见状态到真实完整动作，禁止隐藏、未来、当前手数、赛程特征、奖励及RL。进程会自行完成本轮训练与分析；原automation条目已不存在，不能声称聊天定时唤醒已经配置。持续目标仍未达成，不归档聊天。
