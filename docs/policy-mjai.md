# 雀魂 MJAI 语料转换与训练

2026-10-13 的扩展采集已取得 50,000 场四麻；三麻尚无可用完整语料。新增整场划分扩展、200 场管线实验及游戏动作契约验证见 [50,000 场采集与接入记录](policy-50k.md)。以下保留早期 10,000 场流程的来源与验收记录。

MJAI 现可经过转换用于现有策略模型训练，路径为：

```text
雀魂对局的 MJAI 事件流
  → 完整性与去重检查
  → RiichiEnv 重建合法操作 + 逐座位可见局面
  → 每场一个压缩训练分片和审计记录
  → 按整场划分训练 / 验证 / 测试
  → 流式监督训练 → NumPy .npz 模型
```

模型结构、动作编码及部署接口沿用 [策略模型设计](policy-model.md)。MJAI 本身是事件流，不能直接作为模型输入；转换后的样本仍是 `schemaVersion: 1` 的 `state + action` 契约。

## 数据来源与数量

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

这些数据和模型都在 Git 忽略目录中。仓库只包含代码、测试和不含整场牌谱的验证汇总。

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

本转换器目前只接受四麻完整 MJAI，覆盖出牌、立直、吃、碰、暗杠、大明杠、加杠、自摸、荣和、九种九牌流局及跳过。模型原有的拔北动作接口仍在，但这批数据不能用于验证或训练三麻拔北策略。训练目标是模仿已记录玩家的动作，不是给每个动作提供最优性标签。

## 按场流式训练

2026-10-10 的有限规模验证使用旧分片，其复现命令为：

```sh
.venv/bin/python scripts/policy_train_corpus.py \
  --manifest .local/policy-bulk/training/manifest.jsonl \
  --players 4 --max-games 30 --epochs 1 --threads 2 \
  --output .local/policy-models/throne-mjai-30-games.npz
```

本轮先完成一轮固定语料训练，模型规模沿用现有配置。以下命令使用新的 10,000 场 manifest，其中 8,000 场参与梯度更新，另外两组各 1,000 场分别验证与测试；“10,000 场全量流程”不表示把验证或测试数据用于梯度更新：

```sh
.venv/bin/python scripts/policy_train_corpus.py \
  --manifest .local/policy-validated-20261011/training/manifest.jsonl \
  --split .local/policy-validated-20261011/split.json \
  --players 4 --epochs 1 --batch-size 128 --threads 1 --device cpu \
  --output .local/policy-models/throne-mjai-10000-20261011.npz
```

训练逐场加载和释放样本，按轮打乱对局和场内决策。只有一个候选的窗口不计入训练损失和决策准确率。读取时重新核对压缩文件哈希、样本数、gameId、统一转换器签名及固定源文件绑定；导出必须通过 PyTorch / NumPy 数值和首选动作一致性检查。

报告明确记录 `manifestGames`、`selectedGames`、实际三个集合的数量和每类动作成绩，避免把少量场次验证称作全量训练。一轮监督模仿的准确率不等于实战胜率或已经收敛；本轮不修改主目录和桌面 App，也不自动部署权重。

使用 `--split` 时禁止同时使用 `--max-games`，避免缩减或重新计算已固定的集合。未指定固定划分的旧式小规模实验，仍会随 `--max-games` 改变而重新选场和切分；它的成绩不能作为固定测试集上的直接比较。每次训练从随机初始化开始。

## 回归检查

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_policy_*.py' -v
node --test tests/test_policy_replay.cjs
```

测试包括损坏压缩包、缺失结果、重复牌谱、路径逃逸、来源 / 恢复哈希、固定划分、赛制证据验证、流式训练导出、红牌消耗组合、立直合并、立直后强制摸切、吃碰竞争、多家荣和、振听时序、食替、隐藏信息与未来事件变更不影响既有特征，以及杠后排除。2026-10-10 的实际下载、转换和小规模训练数量保存在 [历史验证汇总](benchmarks/policy-mjai-20261010.json)；本轮结果应读取上表中新的验收、转换及训练报告。
