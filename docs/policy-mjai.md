# 雀魂 MJAI 语料转换与训练

2026-10-13 已取得 **50,000 场雀魂四麻完整 MJAI 和 50,000 场天凤高段位三麻完整 MJAI**。按固定排除规则，现已完成四麻 **49,951 场、29,809,311 条样本**和三麻 **47,063 场、14,887,401 条样本**的全量转换，两者整场失败均为 0。两套模型均已完成 MPS 3 轮训练与最终评估，分别选中验证 NLL 最低的第 3 轮权重，NumPy 导出核验通过。按用户要求，只使用已经筛选的公开来源，不再用额外本地牌谱或数据库／归档记录补足 50,000 场。完整 MJAI、已转换样本和已完成训练分别计数。

四麻采集记录见 [50,000 场采集与接入记录](policy-50k.md)，三麻来源见 [跨平台调查](policy-cross-platform-data.md)；模型及实时接口见 [策略模型设计](policy-model.md)。下文先给出本轮固定语料和训练命令，再保留早期 10,000 场流程与 500 场三麻 pilot，后两者均为历史记录。

MJAI 现可经过转换用于现有策略模型训练，路径为：

```text
雀魂四麻 / 天凤三麻的 MJAI 事件流
  → 完整性与去重检查
  → RiichiEnv 重建合法操作 + 逐座位可见局面
  → 每场一个压缩训练分片和审计记录
  → 按整场划分训练 / 验证 / 测试
  → 流式监督训练 → NumPy .npz 模型
```

模型结构、动作编码及部署接口沿用 [策略模型设计](policy-model.md)。MJAI 本身是事件流，不能直接作为模型输入；转换后的样本仍是 `schemaVersion: 1` 的 `state + action` 契约。

## 固定语料全量转换与 MPS 训练

本轮仍采用“当前可见局面 → 高段位玩家实际动作”的监督模仿目标，没有收益、排名或价值预测标签。全部小局和座位按完整对局归入同一个固定集合；只有 train 集合参与梯度更新。

| 项目 | 三麻 | 四麻 |
| --- | ---: | ---: |
| 合格完整对局 | 47,063 | 49,951 |
| 训练 / 验证 / 测试场数 | 37,651 / 4,706 / 4,706 | 39,961 / 4,995 / 4,995 |
| 全部样本 | 14,887,401 | 29,809,311 |
| 直接动作标签 | 13,882,622 | 24,689,674 |
| `inferred_pass` | 1,004,779 | 5,119,637 |
| 拔北 / 吃 | 1,064,610 / 不适用 | 不适用 / 398,084 |
| 整场转换失败 | 0 | 0 |

四麻保留 `.local/high-rank-50k/split.json` 中的全部既有分区，49 个开发场始终排除。三麻排除前 1,000 个 XML 转换器开发场、3 个真实回归 fixture，以及 1,934 个额外含 `BYE` 的场次；排除并集为 2,937，所有含 `BYE` 的场次共 1,965，其中 31 场已在开发集合内。三麻 500 场 pilot 的原 400 / 50 / 50 分区全部保留；四麻 pilot 200 场原本全部位于正式 train，不把 pilot 内部评估当成正式留出集成绩。

已重验两份原始 50,000 场来源清单及全部压缩文件 SHA；三麻另核验两个数据库 SHA、原 XML SHA、原始段位与完整终局。来源审计为 `.local/high-rank-50k/{four-player-full,three-player-full}/source-audit.json`。三麻固定来源 manifest SHA 为 `80d1aa75122f61b13d4cc0391a2dd5c41cc08d212023488c328ebbde07544032`，split SHA 为 `8b555a88b2b22c2c10e15a18e0b85a459eb62c9976a1167b3ddab3dcca0a8b38`；四麻来源 manifest SHA 为 `638c50eb3f4494e2162a58a5cdc959f7aa9bf8f2db4383dafa5b21fb1b344181`，split SHA 为 `951a9aeb150eea5368acfc4a1d06040d184dae93b304b4ac8541a72d03159d70`。不重排、不补场，也不混入个人或本地录制对局。

以下命令对应本轮实际目录和已冻结配置。转换已经完成；重运行同一转换命令会先验证并恢复已有结果：

```sh
cd /Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013
POLICY_PYTHON=/Users/kenny/Desktop/Maj-Soul-PlusPlus-model/.venv/bin/python

"$POLICY_PYTHON" scripts/policy_convert_mjai.py \
  --manifest .local/high-rank-50k/four-player/manifest.jsonl \
  --split .local/high-rank-50k/split.json \
  --output .local/high-rank-50k/training --limit 49951 --workers 6

"$POLICY_PYTHON" scripts/policy_convert_mjai.py \
  --manifest .local/high-rank-50k/research/cross-platform/tenhou-sanma-mjai/full-source-eligible.jsonl \
  --split .local/high-rank-50k/three-player-full/split.json \
  --tenhou-db-root .local/high-rank-50k/research/cross-platform \
  --output .local/high-rank-50k/three-player-full/training --limit 47063 --workers 4

# 可选：先并行准备特征缓存；训练也会按需创建缺失缓存。
"$POLICY_PYTHON" scripts/policy_prepare_cache.py \
  --manifest .local/high-rank-50k/training/manifest.jsonl \
  --players 4 --encoded-cache .local/high-rank-50k/encoded-cache --workers 2

"$POLICY_PYTHON" scripts/policy_prepare_cache.py \
  --manifest .local/high-rank-50k/three-player-full/training/manifest.jsonl \
  --players 3 --encoded-cache .local/high-rank-50k/encoded-cache --workers 2

"$POLICY_PYTHON" scripts/policy_train_corpus.py \
  --manifest .local/high-rank-50k/training/manifest.jsonl \
  --split .local/high-rank-50k/split.json --players 4 \
  --epochs 3 --batch-size 2048 --game-window 16 --device mps --threads 2 \
  --encoded-cache .local/high-rank-50k/encoded-cache --checkpoint-every-games 1000 \
  --output .local/high-rank-50k/models/four-player-full.npz

"$POLICY_PYTHON" scripts/policy_train_corpus.py \
  --manifest .local/high-rank-50k/three-player-full/training/manifest.jsonl \
  --split .local/high-rank-50k/three-player-full/split.json --players 3 \
  --epochs 3 --batch-size 2048 --game-window 16 --device mps --threads 2 \
  --encoded-cache .local/high-rank-50k/encoded-cache --checkpoint-every-games 1000 \
  --output .local/high-rank-50k/models/three-player-full.npz
```

`--device mps` 使用 Apple GPU，部署仍是 NumPy CPU 推理。`--encoded-cache` 保存未经降精度的每场特征、候选和标签，绑定玩家数、原样本 SHA、样本数及编码器代码签名；不改变样本定义或正式数据划分。缓存准备命令只遍历 manifest 内全部场次，不决定训练分区，正式训练仍必须传入 `--split`。两个玩法可共享缓存目录，缓存键包含玩法和来源绑定。

`--game-window 16` 将最多 16 场 train 数据合并后打乱决策并组成 batch，减少小 batch 的 GPU 开销；仅改变训练样本组织方式，不跨越固定分区，也不减少每轮读取的场数。内存由当前场窗口限制，而非一次加载约 4,470 万条样本。

训练在跨过每 1,000 场的完整窗口边界和每轮结束时，原子保存 `four-player-full.resume.pt` 或 `three-player-full.resume.pt`。断点包括模型、AdamW 优化器、随机数状态、当前轮次、对局顺序与游标、累计损失以及历史最优验证权重。中断恢复时在对应完整训练命令末尾加 `--resume`，并保持来源 manifest、split、编码器／训练器代码和训练参数一致，包含 `--epochs 3`、batch size 和 game window。参数或来源不匹配会拒绝恢复；已经完成最终评估的断点也会拒绝再次恢复。`*.checkpoint.npz` 是按验证 NLL 选出的中间权重，不代表训练和测试已完成。

两份转换报告为 `.local/high-rank-50k/training/report.json`、`three-player-full/training/report.json`，转换器签名均为 `96872ac64e57897511a367b3d25e9f26958a738cbe0ab9de61b6cf8feb6e4f42`。训练日志位于 `.local/high-rank-50k/research/full-training/`。最终 `models/{four-player,three-player}-full.report.json` 已生成，两套作业正常完成，最佳轮次均为 3。三麻正式测试 Top-1 / Top-3 为 **75.333008% / 95.663311%**、NLL **0.672929630**；四麻为 **73.560030% / 94.853761%**、NLL **0.726915647**。两份权重各通过 32 个 MPS PyTorch / NumPy 导出首选一致性检查，logits 最大误差均为 `3.8146973e-6`。实际分区样本数、完整权重 SHA、逐动作结果和限制见 [正式模型结果](policy-model.md#固定语料全量训练2026-10-13)及 [全量训练汇总](benchmarks/policy-full-training-20261013.json)，没有用历史 pilot 指标替代。大明杠测试匹配仍为三麻 0 / 222、四麻 0 / 380，四麻吃为 42.68%；动作模仿准确率不等于实战胜率。模型包和 App 构建另按 [模型包验收流程](policy-bundle.md)核验，本节不声称已安装或通过 GUI／在线对局测试。

## 历史四麻数据来源与数量

数据来自公开的 [nikketryhard/tenhou-houou-mjai](https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai) 数据集，固定版本 `6450bb584cef43ede3b514df48e301a832c6818b`。虽然数据集名称包含 Tenhou，本次选用的文件为 **`majsoul-throne-2026.tar`**，来源分类为雀魂王座之间，没有用天凤记录替代雀魂记录。

该归档共 23,182 份记录，23,179 场通过严格解压、游戏 UUID 与事件内容去重、整场和小局结构检查；3 场因小局缺少结果而排除。有效数据包含 244,242 个小局、24,666,562 个事件，日期为 2026-01-01 至 2026-02-03。完整性检查不是逐个规则裁定的证明。

“王座之间”依据发布者的数据集说明和归档分类。MJAI 没有保留每位玩家的官方段位元数据，因此不能据此声称已经逐人核验段位。它也没有保留官方合法操作列表。数据集标注许可为 `other`；转换工具的许可不等于对原始牌谱权利的授权。固定下载地址与哈希见 [数据来源说明](policy-data-sources.md#public-mahjong-soul-throne-mjai-corpus)。

本地目录（相对仓库根目录）：

| 路径 | 内容 |
| --- | --- |
| `.local/policy-bulk/archives/` | 下载的原始归档 |
| `.local/policy-bulk/corpus/manifest.jsonl` | 23,179 场来源、UUID、日期、三种内容哈希及小局 / 事件数量 |
| `.local/policy-bulk/corpus/data/games/` | 通过检查的原始 MJAI 分片 |
| `.local/policy-bulk/training/manifest.jsonl` | 2026-10-10 旧转换结果，保留供来源追溯，不与修复后的分片混用 |
| `.local/policy-bulk/match-metadata-20261011/official-headers.jsonl` | 19 场经官方原始响应校验的赛制元数据 |
| `.local/policy-validated-20261011/split.json` | 固定的 8,000 / 1,000 / 1,000 场训练、验证、测试划分及源哈希 |
| `.local/policy-validated-20261011/paired-acceptance.json` | 官方原始牌谱与 MJAI 的决策窗口对照验收 |
| `.local/policy-validated-20261011/training/` | 本轮新转换分片、manifest、逐场审计及 report |
| `.local/policy-models/` | 模型权重与训练报告；完成情况以对应报告为准 |

批量数据和模型都在 Git 忽略目录中。仓库保留代码、验证汇总，以及用于回归的少量固定牌谱 fixture。

2026-10-10 的实际交付为 **10,000 场、6,174,881 条训练样本**，整场转换失败 0 场。全部分片及独立审计文件的哈希、来源对应关系和统计总数均已复核；另抽取 100 场、62,255 条样本由真实训练器独立读取，全部接受。最终 manifest 中选取 30 场完成 1 轮 CPU 实验，划分为 24 / 3 / 3 场，共 19,758 条样本，耗时约 27.79 秒；32 个导出检查窗口的首选动作一致，分数最大绝对误差 `4.77e-7`。这不等于已用 10,000 场完成训练。

## 2026-10-11 修复与独立验收

本轮修复振听读取时序、立直后的候选操作和赛制元数据传递。19 场本地官方原始牌谱用于开发对照，覆盖 190 个小局；修复后匹配到的 **10,656 个决策窗口**，候选集合、动作标签、状态平面及全部全局特征均一致，未匹配、歧义匹配及重复使用官方窗口均为 0。官方解析共生成 11,206 个窗口，MJAI 转换生成 10,656 个窗口；该验收只覆盖 MJAI 保留的决策范围，杠后窗口的排除限制仍然存在。19 场对照数据不能代表全部语料的错误率。

新数据划分已固定为 **8,000 场训练、1,000 场验证、1,000 场测试**，每场的所有座位和小局归属同一集合。19 场开发对照和旧 30 场小规模实验全部预先排除；从旧 10,000 场保留 9,962 场，再从同一已审计来源补入 38 场。`split.json` 保存 UUID、压缩源文件及事件内容哈希，转换与训练都必须使用这份文件。验证集用于检查训练结果，测试集独立保留；后续实验沿用此划分，不能根据测试成绩重新选场。

赛制补充只接受可追溯到官方原始响应的头部配置，重新校验 UUID、源文件哈希、官方响应、头部和协议模式文件。当前可核验的 19 场均为 `modeId: 16`、半庄，且已全部排除在正式三个集合之外。因此，本轮固定的 **10,000 场均保留东风 / 半庄未知**，没有使用归档名称、昵称、最终结果或后来是否出现南场补猜赛制。规则引擎对未知赛制使用半庄配置继续回放，并在审计中记录 `ruleEngineMatchLengthAssumed`；模型的 `match.roundCount` 仍为未知。这一批数据不足以验证模型对东风与半庄终局策略的区分。

验收时 Python 策略测试 152 项、官方回放 Node 测试 29 项通过。下文给出固定划分后的转换和一轮全量训练命令；训练完成前，旧样本数和旧 30 场实验结果都不能作为本轮全量结果。新的实际样本数、训练耗时、评估成绩及导出一致性，以本轮 `training/report.json` 和模型的 `.report.json` 为准。

## 安装、审计和转换

在已有 Python 3.12 虚拟环境中安装训练及转换依赖：

```sh
.venv/bin/python -m pip install -r requirements-training.txt -r requirements-mjai.txt
```

规则引擎固定为 `riichienv==0.4.10`，压缩库固定为 `zstandard==0.25.0`。它们只用于离线数据处理，不属于桌面运行时依赖。转换命令拒绝使用其他版本的规则引擎。

从已下载且校验哈希的归档建立语料清单：

```sh
.venv/bin/python scripts/policy_corpus_audit.py \
  .local/policy-bulk/archives/majsoul-throne-2026.tar \
  --output .local/policy-bulk/corpus \
  --limit 23179 \
  --source-url https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai/tree/6450bb584cef43ede3b514df48e301a832c6818b \
  --publisher-room throne
```

在已有官方原始响应归档和已保存的排除名单上，建立赛制侧文件及固定划分：

```sh
.venv/bin/python scripts/policy_match_metadata.py \
  --official-archive .local/policy-official/archive \
  --corpus-manifest .local/policy-bulk/corpus/manifest.jsonl \
  --output .local/policy-bulk/match-metadata-20261011/official-headers.jsonl

.venv/bin/python scripts/policy_freeze_split.py \
  --corpus .local/policy-bulk/corpus/manifest.jsonl \
  --preferred-manifest .local/policy-bulk/training/manifest.jsonl \
  --excluded .local/policy-validated-20261011/excluded-games.json \
  --count 10000 --seed 42 \
  --output .local/policy-validated-20261011/split.json

.venv/bin/python scripts/policy_validate_pairs.py \
  --archive .local/policy-official/archive \
  --corpus .local/policy-bulk/corpus \
  --metadata .local/policy-bulk/match-metadata-20261011/official-headers.jsonl \
  --output .local/policy-validated-20261011/paired-acceptance.json
```

确认对照报告的 `passed` 为 `true` 后，转换固定的 10,000 场：

```sh
.venv/bin/python scripts/policy_convert_mjai.py \
  --manifest .local/policy-bulk/corpus/manifest.jsonl \
  --metadata .local/policy-bulk/match-metadata-20261011/official-headers.jsonl \
  --split .local/policy-validated-20261011/split.json \
  --output .local/policy-validated-20261011/training \
  --limit 10000 --workers 4
```

转换逐场核对固定划分与源文件 SHA256，并生成 `games/<UUID>.jsonl.zst`。中断后使用同一命令恢复；代码签名、来源、逐场赛制元数据或已写入结果发生变化时会拒绝混用，需选择新的输出目录。每个样本都先通过可见状态编码和合法动作匹配，再写入分片。本轮重新生成派生训练数据，原始 MJAI、官方响应和旧转换结果保留不变。

## 标签和信息边界

- 只导出当前行动者的手牌、自己的摸牌与公开信息；对手暗手、对手摸牌、牌山、未来事件、最终结果和昵称不进入模型特征。整场隐藏牌仅供规则引擎回放，不直接供模型读取。
- 合法候选由规则引擎生成，然后匹配实际动作。立直与随后的出牌合为一个候选；红五、手切 / 摸切、吃碰杠的消耗牌均保留。庄家首张出牌按客户端语义标记为非摸切。
- 已立直后的普通自动摸切不作为玩家自由选择的出牌窗口。存在自摸、杠等特殊操作时，候选为可用的特殊操作与跳过；实际自动摸切只在能确认是刚摸入的同一张牌时用于推断跳过。这样既排除强制出牌噪声，也保留放弃特殊操作的决策标签。
- 只有下家正常摸牌明确结束响应窗口时，才把未鸣牌标为 `inferred_pass`。被碰、杠或荣和抢先的吃牌等响应被遮蔽，不能直接当作跳过；多家荣和使用同一冻结窗口匹配。
- 自己弃和导致的同巡振听与立直后永久振听独立跟踪，包括牌形已和但没有合法役的窗口；响应关闭后才更新弃和状态。自弃牌振听在本人完成出牌时，根据当时听牌集合与本人的牌河缓存，不能用摸牌后 14 张手牌的空听牌集合把它清除。
- 官方 `zhenting` 可能已包含本次响应之后的振听，摸牌消息也可能仍保留旧的同巡标志。官方回放据此保留响应前状态供当前决策使用，自己的摸牌清除同巡振听，但保留自弃牌与立直后永久振听；杠或拔北改变手牌、又缺少足够信息区分振听来源时，保留未知，避免猜测。
- 当前规则库的事件回放接口无法可靠还原杠后的所有响应和振听状态。因此保留杠动作本身，**从杠发生后到该小局结束的窗口全部排除**，下一小局恢复。`hand_suffix_after_kan` 统计杠事件数，并不是被排除决策的精确数量。
- 东风 / 半庄元数据只从经原始响应验证的侧文件传入，并跨 `start_game` / `start_kyoku` 重置保留；没有证据时 `match.roundCount` 为未知，不根据未来事件推断。

本转换器接受雀魂四麻完整 MJAI，以及带原始 XML 证据的天凤三麻完整 MJAI。四麻覆盖出牌、立直、吃、碰、暗杠、大明杠、加杠、自摸、荣和、九种九牌流局及跳过；三麻禁吃，并增加拔北。三麻和四麻分别训练、导出与加载模型，监督目标均为高段位玩家的实际动作，没有收益或价值预测头。

## 天凤三麻入口与 500 场样本验收

本节保留全量转换之前的历史 pilot 命令和测量，正式语料以本文开头的 47,063 场固定集合为准。

三麻输入为 `.local/high-rank-50k/research/cross-platform/tenhou-sanma-mjai/` 下的完整 MJAI，原始 XML 仍在同级研究目录的 `pathofhouou-2016.db`、`pathofhouou-2017.db` 中。新的 `--tenhou-db-root` 参数是必需的：转换器只读 SQLite，核验 XML SHA256、`GO` 规则头、三席 `UN` 头和七段至天凤位的原始段位。`GO` 决定场长并选择 `GameRule.default_tenhou()`，不借用雀魂房间编号，也不从未来南场事件推断场长。

本轮先排除开发 XML 转换器时使用过的前 1,000 场，再从余下 49,000 场按固定哈希顺序提取样本。以下命令在独立工作目录运行，复用已经安装的 Python 3.12 环境；原始 50,000 场清单保持不变：

```sh
cd /Users/kenny/Desktop/Maj-Soul-PlusPlus-training-20261013
/Users/kenny/Desktop/Maj-Soul-PlusPlus-model/.venv/bin/python scripts/policy_convert_mjai.py \
  --manifest .local/high-rank-50k/research/cross-platform/tenhou-sanma-mjai/pilot-source-remaining49000.jsonl \
  --tenhou-db-root .local/high-rank-50k/research/cross-platform \
  --output .local/high-rank-50k/three-player-pilot-training \
  --limit 500 --workers 2
```

已生成 500 场、161,180 条样本，压缩后 11,342,640 字节。过程中 18 场因 XML 含 `BYE` 被整场排除，继续补入候选直到达到 500 场；没有把掉线期间自动动作归为高段位玩家选择。该过滤连终局后的 `BYE` 也排除，是保守的训练选择，不撤销原始牌谱的完整性检查结论。报告为 `.local/high-rank-50k/three-player-pilot-training/report.json`，转换器签名为 `96872ac64e57897511a367b3d25e9f26958a738cbe0ab9de61b6cf8feb6e4f42`。

| 样本标签 | 数量 |
| --- | ---: |
| 出牌 | 127,265 |
| 拔北 | 11,518 |
| 碰 | 4,218 |
| 暗杠 / 大明杠 / 加杠 | 273 / 21 / 168 |
| 立直 | 3,166 |
| 自摸 / 荣和 | 1,816 / 1,689 |
| 九种九牌流局 | 125 |
| 跳过 | 10,921 |

其中 150,259 条标签直接来自已记录动作，10,921 条是满足关闭条件的 `inferred_pass`。报告未出现标签不在候选集合中的错误；这只验证本轮保留的样本，不是对其余 49,500 场或全部边界动作的证明。

三麻可见局面使用三个座位、开局摸牌后 54 张剩余牌墙，以及公开拔北数量。红牌、吃碰杠来源、消耗牌和加杠副露索引沿用统一动作合同。拔北的手切／摸切必须由 `_tenhou` 保存的物理牌证据确定，缺少证据时排除标签；庄家开局的来源参数按雀魂客户端归一化。普通拔北与补牌继续形成后续决策。

RiichiEnv 0.4.10 的 MJAI 重放漏设拔北补牌的岭上标志，可能使副露无役手缺少合法自摸候选。本提取器根据已公开的 `kita → tsumo` 事件补齐标志，并在弃牌和下次普通摸牌时复位。独立最小回归验证仅有岭上役时出现自摸候选，后续同形普通摸牌没有残留自摸候选。无役形听漏和继续按 [天凤官方手册](https://tenhou.net/man/)跟踪同巡振听。

杠动作本身保留，但杠后的该小局后续窗口仍排除；本轮有 495 次此类杠事件。拔北时若他家形听 North，当前提取器尚未验收该抢北响应，排除该小局后续窗口，本轮触发 3 次。隐藏听牌只用于规则重放和决定是否排除窗口，不写入模型特征；这种过滤可能改变保留样本的集合。竞争鸣牌另有 137 个响应被遮蔽，不猜测其跳过标签。

`sourcePlatform`、`ruleEngineRules`、原始 `GO`、段位与来源哈希用于审计，不是网络特征；经证据确定的场长仍是可见局面特征。实时雀魂建议使用当前服务器提供的合法操作集合。源规则与目标规则差异仍可能改变动作机会或玩家偏好，迁移质量必须由雀魂留出集另行检验。这 500 场用于有限管线实验，不能据此宣称三麻泛化棋力或 50,000 场均已训练。

## 按场流式训练

2026-10-10 的有限规模验证使用旧分片，其复现命令为：

```sh
.venv/bin/python scripts/policy_train_corpus.py \
  --manifest .local/policy-bulk/training/manifest.jsonl \
  --players 4 --max-games 30 --epochs 1 --threads 2 \
  --output .local/policy-models/throne-mjai-30-games.npz
```

以下保留 2026-10-11 的 10,000 场固定语料复现命令，其中 8,000 场参与梯度更新，另外两组各 1,000 场分别验证与测试；“10,000 场全量流程”不表示把验证或测试数据用于梯度更新。2026-10-13 的实际全量配置以上文两套 manifest 为准：

```sh
.venv/bin/python scripts/policy_train_corpus.py \
  --manifest .local/policy-validated-20261011/training/manifest.jsonl \
  --split .local/policy-validated-20261011/split.json \
  --players 4 --epochs 1 --batch-size 128 --threads 1 --device cpu \
  --output .local/policy-models/throne-mjai-10000-20261011.npz
```

训练逐场加载和释放样本，按轮打乱对局和场内决策。只有一个候选的窗口不计入训练损失和决策准确率。读取时重新核对压缩文件哈希、样本数、gameId、统一转换器签名及固定源文件绑定；导出必须通过 PyTorch / NumPy 数值和首选动作一致性检查。

报告明确记录 `manifestGames`、`selectedGames`、实际三个集合的数量和每类动作成绩，避免把少量场次验证称作全量训练。一轮监督模仿的准确率不等于实战胜率或已经收敛；该历史实验未修改主目录或桌面 App，也未自动部署权重。当前全量模型的发布和构建应读取新的模型包验收记录。

使用 `--split` 时禁止同时使用 `--max-games`，避免缩减或重新计算已固定的集合。未指定固定划分的旧式小规模实验，仍会随 `--max-games` 改变而重新选场和切分；它的成绩不能作为固定测试集上的直接比较。未指定 `--resume` 时从随机初始化开始；恢复方式见上文，不通过载入历史 pilot 权重重新开始本轮训练。

## 回归检查

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_policy_*.py' -v
node --test tests/test_policy_replay.cjs
```

三麻新增 8 条回归覆盖三场真实完整牌谱、各类杠和拔北、物理来源不明时剔除、源规则与元数据、断线／段位／XML 哈希，以及岭上补牌标志与复位。

测试包括损坏压缩包、缺失结果、重复牌谱、路径逃逸、来源 / 恢复哈希、固定划分、赛制证据验证、流式训练导出、红牌消耗组合、立直合并、立直后强制摸切、吃碰竞争、多家荣和、振听时序、食替、隐藏信息与未来事件变更不影响既有特征，以及杠后排除。2026-10-10 的实际下载、转换和小规模训练数量保存在 [历史验证汇总](benchmarks/policy-mjai-20261010.json)；本轮结果应读取上表中新的验收、转换及训练报告。
