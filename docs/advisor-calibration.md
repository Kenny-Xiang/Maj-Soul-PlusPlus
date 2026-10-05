# 放炮概率校准的数据契约与离线入口

截至本次仓库检查，**尚未完成实战校准**。`scripts/advisor_calibration.py`
提供可重复的数据审计、观测提取、分层拟合与留出集评估；它不会修改
`src/advisor.py` 的参数，也不会自动把拟合结果装进 App。

## 已有证据与实际缺口

本次检查的 `tests/fixtures/recording` 有 60 个消息帧、48 个动作（step 63–110），
没有开局或终局。22 次摸牌里 16 次隐藏牌面。`turn.json` 是另外的开局快照。
三个 `advisor*cases.json` 文件共有 49 个固定状态，主要用于人工构造的行为回归。
这些数据不能恢复每个决策时各对手是否听牌、是否可合法荣和某张牌，以及命中时
弃牌者实际支付多少。仅用终局赢家、流局亮牌，或“这张牌没被荣和”作为负例，
都会引入选择偏差或错误标签。已有事件解码器也不是完整牌谱真值导出器。

可以随时重做检查，报告会包含输入文件哈希和实时计数：

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_calibration.py audit \
  --output /tmp/advisor-calibration-audit.json
```

**当前缺的是完整且可信的牌谱及经审阅的导出器/标签器，不是新的人工概率常量。**
`.04 + .018 × 河长 + .14 × 面子数`、中张形状率、筋折扣、无明确役权重等
仍是未由实战拟合的启发式。摸切/手出和河的顺序已经在提取结果中保留；本次没有
凭这些字段另造系数。各终局、弃和、排名偏好等决策近似也不因本入口而获得校准证明。

## 真值定义与计数单位

| 层 | 一条观测的单位 | 标签与分母 |
| --- | --- | --- |
| `tenpai` | 一次本人弃牌前决策 × 一个对手 | 对手此刻是否结构听牌。包含无役/振听的结构听牌；不能拿最终是否和牌替代。每个对手只计一次，不按本人候选牌数重复。 |
| `ronGivenTenpai` | 已真听牌的对手 × 一张本人持有的不同实体牌编码 | 假设本人现在弃此牌，对手是否**合法**荣和；须检查役、整手振听、同巡/立直振听、事件役与规则。赤 `0p` 和普通 `5p` 分开。 |
| `paymentGivenRon` | 上一层标签为真的候选牌 | 此次荣和弃牌者的付款，含本场、不含既存立直棒；保留满贯等非线性计分。不是胜者总收入。 |
| `dealIn` | 所有对手 × 所有候选牌 | 两个原始概率之积的附加一致性评估，标签仍为合法荣和；不另拟合成第四个分数。 |

这里的“候选牌”覆盖本人手中每个不同编码，供条件风险诊断。它不是只保留模型
实际选中的牌，也不是声称所有这些牌都能在当前操作约束下选择。立直锁定等
行动合法性应在决策评估中另行限制。没有真实继续打某张牌的数据时，不能把
实际打另一张牌之后的回报贴到这张牌上。

对手可能主动放过荣和，多家同时荣和及包牌也需要单独处理。
该入口评估的是逐对手的合法荣和资格与对应弃牌付款，不能用它直接证明
`1 − ∏(1 − p)` 的独立性假设，或完整牌局收益模型正确。

## 输入 schema 1

入口接受**完整牌谱经过外部导出器和标签器审阅后**生成的单个 JSON 文档。
它不会从截断的 `capture.json` 猜隐藏手牌。顶层结构如下（`decisions` 的对象见下文）：

```json
{
  "schemaVersion": 1,
  "source": {
    "kind": "complete-replay",
    "exporter": "reviewed-exporter-name-and-version",
    "labeler": "reviewed-labeler-name-and-version",
    "ruleset": "majsoul-standard",
    "labelMethod": "omniscient-state-before-discard"
  },
  "matches": [{
    "id": "stable-match-id",
    "startedAt": "2026-01-01T10:00:00+08:00",
    "endedAt": "2026-01-01T10:40:00+08:00",
    "replay": {"path": "replays/match.json", "sha256": "actual-sha256-of-file"},
    "decisions": []
  }]
}
```

每个 `decision` 必须提供：

- `roundId`：整场内唯一的小局标识，包含连庄本场；`step`：该小局内的决策步。
- `at`：带时区的决策时间，位于整场起止时间内。
- `publicState`：决策时本人视角的状态，要求 `canDiscard=true`、
  `handComplete=true`、`historyComplete=true`，`lastStep` 与 `step` 一致。
  必须有 `selfSeat`、`playerCount`、`hand`、`rivers`、`melds`。
  本人牌数为 `14 − 3 × 本人面子组数`，公开实体枚数必须有效。
  `round` 的 `chang`、`ju`、`ben`、`doras`、`north`、`riichi`、
  `riichiPending`、`riichiStep`、`left` 必须按真实状态提供，
  `doubleRiichi` 可省略（默认无双立直）。
- 每条河牌需要 `tile`、`step`、布尔 `moqie`，被鸣走的牌还须正确设置 `called`。
  河牌严格按 step 排序。每个副露需要 `type`、`tiles`、形成或更新的 `step`，
  有来源信息时保留 `froms`。加杠用当前加杠更新 step。所有 step 不得超过决策步。
- `opponents`：每个对手恰好一个对象。形如
  `{"seat":1,"tenpai":true,"tiles":{"1z":{"legalRon":true,"lossPoints":2000},...}}`。
  `tiles` 的键必须与本人手中所有不同牌编码完全相同；不能漏掉安全牌或负例。
  非命中必须付款为 0，命中必须真听牌且付款为有限正数。

一场对应一个原始牌谱文件，路径相对数据集文件。脚本验证 SHA-256，拒绝相同
文件被不同场 ID 重复纳入，并拒绝重复 `(matchId, roundId, step, selfSeat)`。
**哈希仅证明文件身份，不能证明来源真实、标签正确或采样无偏。**
完整性标志、牌谱来源、采样覆盖、全手牌重建、振听与计分标签仍必须由外部审阅
保证。若原始来源没有副露形成 step，导出器应从事件重建，不能填写猜测值。

预测器只接收脚本构造的公开字段白名单；标签对象不传入预测器。河、副露和局数
也逐层裁剪，因此 `opponentHands`、未来分数、终局赢家、未揭示里宝等附带数据
不进入输入。这不能自动检查“某个被填写在公开字段里的值其实来自未来”的语义
错误，导出器仍须在事件时间截断。隐藏状态只能进入离线标签侧。

`source.kind="synthetic-test"` 专供流程测试；报告会标为
`synthetic-pipeline-check`。禁止把它改成 `complete-replay` 来获取实战证据标签。

## 提取与留出评估

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_calibration.py extract \
  --dataset /path/to/reviewed-export.json --output /tmp/risk-observations.json

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/advisor_calibration.py evaluate \
  --dataset /path/to/reviewed-export.json \
  --train-end 2026-07-01T00:00:00+08:00 \
  --validation-end 2026-08-01T00:00:00+08:00 \
  --output /tmp/risk-calibration-report.json
```

`extract` 直接从当前 `advisor._opponents/_danger` 获取三个分量，保留公开输出的
概率精度；同时记录模型名、源码 SHA-256、数据集 SHA-256、原始牌谱哈希、
三/四麻、立直、面子数、河长、手出次数及原河序列。独立命令不修改应用状态。

切分规则由明确时间界限决定，整场不可拆开：

1. 整场结束早于 `train-end` 的场属于训练集。
2. 整场开始不早于 `train-end`，结束早于 `validation-end` 的场属于验证集。
3. 整场开始不早于 `validation-end` 的场属于测试集。
4. 跨越界限的整场排除并列出，防止同场相关片段进入不同集合。

诊断候选仅由训练集拟合：听牌率和条件荣和率各自采用 10 个等宽概率箱的观测
频率（`--bins` 可预先指定）；空箱回退原预测，确定性 0/1 不改动并另外计数矛盾。
付款候选是训练集 `总真付款 / 总预测付款` 的单一比例。
这些是可解释的基线候选，稀疏分箱会过拟合，单个倍率不能修复计分结构差异；
脚本不会据此宣称校准成功。验证集/测试集标签绝不参与拟合，也不据测试集自动
挑箱数或系数。缺少任一时间分区时标注覆盖不足。

报告分别给出原模型与候选的 Brier、log loss、ECE、分箱可靠性与阳性数；
付款报告 MAE、RMSE、平均有符号误差。`dealIn` 只评估原始两分量乘积，
没有把三个独立诊断候选拼装成新部署模型。所有层保留样本数；空层只报 `count=0`，
不会输出虚假的零误差。一个场里的多个决策和备选牌相关，行数不是独立样本数。

投入运行前仍需要：足够完整对局；预先确定的代表性抽样；逐规则核对标签；
按三/四麻、立直/副露、巡目等分层检查；以整场为单位的不确定性评估；新时间段
重复验证；以及独立的策略收益实验。本次入口提供重跑和审阅基础，没有代替这些工作。

## 本次验证

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover \
  -s tests -p 'test_advisor_calibration.py'
```

10 项合成流程测试验证分母、输入不变、隐藏字段隔离、历史时序、完整标签、
重复场/步骤拒绝、三麻和赤牌身份、整场跨界排除、留出标签不参与拟合、
已知解析指标与确定性边界。**这 10 项测试通过不等于实战概率被校准。**
