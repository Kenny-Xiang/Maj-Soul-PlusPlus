# 雀魂牌谱策略模型

第一版实现了「官方格式牌谱 → 可见局面与动作标签 → 监督训练 → 模型导出 → 离线推理 → 可选客户端接入」。它学习牌谱玩家在合法动作之间的选择。输出的 `policyProbability` 是候选动作之间的偏好分布，不是和牌率、胜率或动作最优性的证明。

当前交付包括官方格式牌谱的 **smoke 样例模型**，以及 [MJAI 转换和按场流式训练](policy-mjai.md)。前者返回 `status: analysis`，现有自动打牌入口不会执行该模型的建议；后者已用公开雀魂王座之间记录完成小规模训练验证。两者均不代表已达到实战棋力。三麻的数据、动作、训练和推理代码已实现，并有拔北等合成回归；本次没有获得足以验证真实三麻训练的数据。

## 模型与动作

结构参考 [Akagi v3 原生模型](https://github.com/shinkuan/Akagi/tree/cd68865f9e93eddcda6451cd18874a6f68c5fb49)，采用 64 通道卷积、3 个残差块和 256 维隐藏层。本项目独立实现可变数量的候选动作评分，不导入 Akagi 权重。

| 部分 | 当前实现 |
| --- | --- |
| 牌面输入 | `54 × 34`：手牌张数、红牌、摸牌、宝牌指示牌、已见及未见张数、各家牌河与副露摘要 |
| 全局输入 | 56 维：相对座位、点数、庄家、场风、立直与待确认立直、拔北、剩余牌数、本场、供托、振听及信息是否已知等 |
| 动作输入 | 每个候选 134 维：动作类型、具体牌、被鸣牌、消耗牌、来源座位、副露索引、手切／摸切 |
| 输出 | 每个合法候选一个分数，在该窗口的合法候选上做 softmax |
| 参数量 | 756,545 |
| 训练 | PyTorch；交叉熵、AdamW、梯度裁剪；按验证集 NLL 选择权重 |
| 部署 | NumPy CPU；非 pickle 的 `.npz`，加载时检查版本、特征签名、玩法、形状和有限数值 |
| 玩法 | 三麻、四麻独立训练、独立加载；仅普通段位规则 |

支持出牌、立直、吃、碰、大明杠、暗杠、加杠、拔北、自摸、荣和、九种九牌流局以及跳过，共 12 种语义动作。红五与普通五分别编码；同牌手切与摸切也分别建候选。吃碰杠保留消耗牌，不能仅输出一个操作类别。

`policy_actions.legal_actions(state)` 从操作列表生成完整候选，不预先裁掉和牌、跳过或低启发式分数的动作。不完整、矛盾或过期的操作窗口会拒绝推荐。官方格式提取器要求记录中的服务端操作列表；MJAI 转换器使用固定版本的规则引擎重建操作列表，并明确标记为 `riichienv-reconstructed`。两条路径的牌谱标签都必须恰好对应一个合法候选；不能根据实际发生的动作向候选集合补入标签。

官方格式输入采用与实时客户端相同的 `core.cjs` 状态更新，MJAI 则投影到同一可见局面契约。回放逐座位投影，模型只读白名单字段：不会使用对手暗手、对手摸牌、牌山、里宝牌、未来事件、最终排名、账号或昵称。牌河时序在此版以计数和最新位置摘要表示，没有完整序列编码器，也没有价值网络或强化学习训练。

## 安装与复现样例

在仓库根目录执行。需要 Python 3.12 和 Node.js 18+；训练依赖与应用依赖分开安装。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-training.txt

# 下载固定版本、固定哈希的一场公开牌谱。
.venv/bin/python scripts/policy_fetch.py \
  --public-sample four-player-210815 \
  --output .local/policy-data/public-four-player.normalized.json

# 抽取各座位在当时可见的局面、动作及排除原因。
node scripts/policy_extract.cjs \
  .local/policy-data/public-four-player.normalized.json \
  --output .local/policy-data/four-player.samples.jsonl \
  --audit .local/policy-data/four-player.audit.json

# 单场只用于管线验证；必须显式选择 --smoke。
.venv/bin/python scripts/policy_train.py \
  .local/policy-data/four-player.samples.jsonl \
  --players 4 --epochs 10 --device cpu --threads 2 --smoke \
  --output .local/policy-models/four-player-smoke.npz

# 对第一个决策窗口推理；--line 可选择其他窗口。
.venv/bin/python scripts/policy_predict.py \
  .local/policy-models/four-player-smoke.npz \
  .local/policy-data/four-player.samples.jsonl --line 1
```

预测输出包含 `best`、所有排序后的 `candidates`、稳定的 `actionId`、`policyProbability`、模型哈希和耗时。也可以传入单个可见局面的 JSON，而非样本 JSONL。

数据由第三方公开仓库保存，内容是雀魂官方牌谱格式；不是雀魂官方发布的训练数据集。下载地址、版权说明、哈希、二进制导入和 `--head-json` 用法见[牌谱数据来源](policy-data-sources.md)。本次未使用登录凭证或私人对局记录。外部完整牌谱、训练权重和环境全部放在 Git 忽略的 `.local/`、`.venv/` 中。

## 用更多牌谱训练

先用 `policy_fetch.py --input` 导入自己已有的官方导出，再逐场用 `policy_extract.cjs` 生成 JSONL。普通训练不加 `--smoke`：

```sh
.venv/bin/python scripts/policy_train.py \
  .local/policy-data/game-a.samples.jsonl \
  .local/policy-data/game-b.samples.jsonl \
  .local/policy-data/game-c.samples.jsonl \
  --players 4 --epochs 10 \
  --output .local/policy-models/four-player.npz
```

脚本至少要求同玩法的 3 场不同完整对局，以建立互不重叠的训练、验证和测试集合；3 场只是代码最低门槛，不是充分的数据量。同一场的所有小局、座位与决策都放在同一集合。默认按稳定哈希约 80%／10%／10% 划分，验证与测试各至少 1 场。重复决策去重，冲突标签报错；不能通过给同一场改名来扩充数据。

三麻使用相同命令加 `--players 3`，输入必须含真实三麻样本。当前公开样例是四麻，不能生成三麻训练模型。`policy_train.py` 一次将特征读入内存，适合初期验证；大语料使用新增的 `policy_train_corpus.py`，按 manifest 逐场加载 `.jsonl.zst` 分片，内存不随总场数增长。转换可以恢复，训练暂不支持优化器断点续训。MJAI 下载、转换、训练命令见 [MJAI 训练指南](policy-mjai.md)。

报告与权重同名，后缀为 `.report.json`，包括源文件哈希、样本类别、分组、逐轮损失、Top-1／Top-3、NLL、各动作准确率及宏平均。只有一个合法动作的窗口单独计数，不计入决策准确率或训练损失。普通训练只用验证集挑选权重，测试集用于最终评估；样例训练的验证、测试指标为 `null`。模型在临时文件中导出，前 32 个样本通过 PyTorch／NumPy 数值与首选动作一致性检查后才发布至指定输出路径。

## 可选接入 Maj-Soul++

默认启动行为保持原有建议引擎，不要求 NumPy 或 PyTorch。只有设置模型环境变量才启用策略后端；运行时只需 `requirements-policy.txt` 中的 NumPy。源码应用本身还需原有构建依赖：

```sh
.venv/bin/python -m pip install -r requirements-build.txt -r requirements-policy.txt

MAJSOUL_POLICY_MODEL_4P="$PWD/.local/policy-models/four-player-smoke.npz" \
  .venv/bin/python src/monitor.py
```

三麻使用 `MAJSOUL_POLICY_MODEL_3P`，可同时设置两个路径。配置缺失的玩法、加载失败、状态不完整或模型不匹配时，浮层会显示不可用原因。浮层按模型偏好列出前三项，保留红牌、手切／摸切与鸣牌消耗牌的区别。

`smoke` 权重仅展示。普通 `behavior-cloning` 权重可产生 `ready` 建议，继续经过既有的局面键、动作提交与服务器回执检查；自动打牌开关仍默认关闭。模型训练成功本身不代表达到自动实战所需棋力。这次没有开启真实对局、替换桌面 App 或验证模型的原生图形展示，也没有修改 PyInstaller 打包配置；上述接入以源码运行验证为范围。

模型输出直接携带实际动作参数，执行入口会根据当前服务端操作列表再次验证。弃牌／立直保留实体牌与 `moqie`，吃碰杠按实际消耗牌匹配服务端组合索引，加杠还须匹配已有碰牌；三麻拔北保留手中北／摸到北的区别。吃、碰、大明杠及响应窗口跳过使用 `inputChiPengGang`；弃牌、立直、暗杠、加杠、拔北、自摸、荣和、九种九牌及自己操作窗口跳过使用 `inputOperation`。

2026-10-13 新增跨语言集成验证：测试先导出具有确定性测试权重的 NPZ，经真实 `PolicyAdvisor` 生成并序列化建议，再交给真实 `unity_actions.js` 和 `unity_transport.js`，在内存 WebSocket 上核对协议请求、服务器 ACK 和权威动作回显。36 个提交用例覆盖全部 12 种动作、四麻／三麻、红牌、手切／摸切、非零组合索引、两种确认到达顺序与重复提交阻止；另验证过期局面和 `smoke` 建议不会提交。测试不建立网络连接，也不证明真实客户端或模型棋力已通过验证。

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_policy_unity_integration.py -v
```

## 本次验证记录（2026-10-10）

公开四麻整局包含 828 个结果事件、9 个小局，得到 489 个决策窗口及 486 条样本：484 条由明确请求确定，2 条由实际执行动作确定。3 个受竞争动作遮蔽的响应被排除；另有 17 个行动时点没有录下操作列表，也被排除。训练样本包括 384 次出牌、64 次跳过、15 次碰、8 次吃、7 次立直、5 次荣和、3 次自摸。

| 检查 | 实测结果与边界 |
| --- | --- |
| 样例训练 | CPU，10 轮；逐轮训练损失从 2.00148 降至 1.57526；耗时约 4.50 秒 |
| 导出一致性 | 32 个窗口，最大分数绝对误差 `3.58e-7`，首选动作全部一致 |
| 完整样本推理 | 486／486 次预测属于对应合法候选集合 |
| NumPy 推理 | 预热后中位 0.379 ms、P95 0.474 ms；包括候选生成和特征编码，不包括 IPC／界面，测量时可能与测试并行 |
| 数据独立性 | 仅 1 场，因此没有留出集泛化成绩或棋力结论 |
| 真实数据覆盖 | 此场没有杠、拔北、九种九牌；这些动作另有合成回归。完整真实三麻、完整真实原始二进制牌谱仍待验证 |
| 源码回归 | Node 386 项、Python 582 项通过，其中策略 Python 测试 53 项 |
| 原生图形检查 | WebKit 回放空回调失败在未修改的 `3e7f578` 基线同样出现；浮层检查另报 `WKErrorDomain Code=5`。完整脚本因此退出 1，GUI 尚未验证通过 |

验证汇总保存在 [policy-smoke-20261010.json](benchmarks/policy-smoke-20261010.json)。运行策略测试：

```sh
node --test tests/test_policy_replay.cjs tests/test_overlay.cjs tests/test_unity_actions.cjs
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_policy_*.py' -v
```

`scripts/test.sh` 已纳入策略测试；没有安装可选训练依赖时，模型相关 Python 测试会跳过。全量测试另需 macOS 图形会话。源码测试通过与原生界面验证是两项独立结论。
