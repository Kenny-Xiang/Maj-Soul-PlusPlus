# 雀魂 MJAI 语料转换与训练

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
| `.local/policy-bulk/training/manifest.jsonl` | 可训练分片清单、转换器签名、源哈希、样本数及逐场审计 |
| `.local/policy-bulk/training/report.json` | 转换数量、动作覆盖和排除原因 |
| `.local/policy-models/` | 小规模验证模型与训练报告 |

这些数据和模型都在 Git 忽略目录中。仓库只包含代码、测试和不含整场牌谱的验证汇总。

2026-10-10 的实际交付为 **10,000 场、6,174,881 条训练样本**，整场转换失败 0 场。全部分片及独立审计文件的哈希、来源对应关系和统计总数均已复核；另抽取 100 场、62,255 条样本由真实训练器独立读取，全部接受。最终 manifest 中选取 30 场完成 1 轮 CPU 实验，划分为 24 / 3 / 3 场，共 19,758 条样本，耗时约 27.79 秒；32 个导出检查窗口的首选动作一致，分数最大绝对误差 `4.77e-7`。这不等于已用 10,000 场完成训练。

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

.venv/bin/python scripts/policy_convert_mjai.py \
  --manifest .local/policy-bulk/corpus/manifest.jsonl \
  --output .local/policy-bulk/training \
  --limit 10000 --workers 4
```

转换按 UUID 稳定哈希选场，逐场核对源文件 SHA256，并生成 `games/<UUID>.jsonl.zst`。中断后使用同一命令恢复；代码签名、来源或已写入结果发生变化时会拒绝混用，需选择新的输出目录。每个样本都先通过可见状态编码和合法动作匹配，再写入分片。

## 标签和信息边界

- 只导出当前行动者的手牌、自己的摸牌与公开信息；对手暗手、对手摸牌、牌山、未来事件、最终结果和昵称不进入模型特征。整场隐藏牌仅供规则引擎回放，不直接供模型读取。
- 合法候选由规则引擎生成，然后匹配实际动作。立直与随后的出牌合为一个候选；红五、手切 / 摸切、吃碰杠的消耗牌均保留。庄家首张出牌按客户端语义标记为非摸切。
- 只有下家正常摸牌明确结束响应窗口时，才把未鸣牌标为 `inferred_pass`。被碰、杠或荣和抢先的吃牌等响应被遮蔽，不能直接当作跳过；多家荣和使用同一冻结窗口匹配。
- 自己弃和导致的同巡振听与立直后永久振听独立跟踪。自弃牌振听由当前听牌集合和本人的牌河判断。
- 当前规则库的事件回放接口无法可靠还原杠后的所有响应和振听状态。因此保留杠动作本身，**从杠发生后到该小局结束的窗口全部排除**，下一小局恢复。`hand_suffix_after_kan` 统计杠事件数，并不是被排除决策的精确数量。
- 东风 / 半庄元数据在这批 MJAI 中不完整，`match.roundCount` 保留未知，不根据后来是否出现南场推断。

本转换器目前只接受四麻完整 MJAI，覆盖出牌、立直、吃、碰、暗杠、大明杠、加杠、自摸、荣和、九种九牌流局及跳过。模型原有的拔北动作接口仍在，但这批数据不能用于验证或训练三麻拔北策略。训练目标是模仿已记录玩家的动作，不是给每个动作提供最优性标签。

## 按场流式训练

先进行有限规模验证：

```sh
.venv/bin/python scripts/policy_train_corpus.py \
  --manifest .local/policy-bulk/training/manifest.jsonl \
  --players 4 --max-games 30 --epochs 1 --threads 2 \
  --output .local/policy-models/throne-mjai-30-games.npz
```

不加 `--max-games` 才会使用整个 manifest，以下是全语料训练命令，不代表本次已经完成该训练：

```sh
.venv/bin/python scripts/policy_train_corpus.py \
  --manifest .local/policy-bulk/training/manifest.jsonl \
  --players 4 --epochs 10 --threads 2 \
  --output .local/policy-models/throne-mjai.npz
```

训练逐场加载和释放样本，按轮打乱对局和场内决策。整场所有座位与小局始终在同一集合，默认约 80% / 10% / 10% 划分。只有一个候选的窗口不计入训练损失和决策准确率。读取时重新核对压缩文件哈希、样本数及 gameId；导出必须通过 PyTorch / NumPy 数值和首选动作一致性检查。

报告明确记录 `manifestGames`、`selectedGames`、实际三个集合的数量和每类动作成绩，避免把少量场次验证称作全量训练。小规模权重仅用于验证管线，本次没有将它部署到桌面 App。

`--max-games` 改变时，所选对局及切分会重新计算；不同规模实验不应被当作同一固定测试集上的直接比较。每次训练从随机初始化开始。

## 回归检查

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_policy_*.py' -v
```

测试包括损坏压缩包、缺失结果、重复牌谱、路径逃逸、来源 / 恢复哈希、流式训练导出、红牌消耗组合、立直合并、吃碰竞争、多家荣和、振听、食替、隐藏信息与未来事件变更不影响既有特征，以及杠后排除。实际下载、转换和训练数量以 [本次验证汇总](benchmarks/policy-mjai-20261010.json) 为准。
