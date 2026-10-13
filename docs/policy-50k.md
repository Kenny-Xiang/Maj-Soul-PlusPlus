# 高段位 MJAI 采集、训练设计与游戏动作接入

本轮使用独立目录 `Maj-Soul-PlusPlus-training-20261013`。完整牌谱、权重与逐场审计位于 Git 忽略的 `.local/high-rank-50k/`；原始模型工作目录、主仓库和桌面 App 保留。

后续扩大到其他平台，已取得并转换 50,000 场天凤三麻 MJAI；来源、规则差异及转换验收见 [跨平台牌谱调查](policy-cross-platform-data.md)。这些牌谱独立保存，未计入下表的“雀魂三麻”；其中 500 场已完成独立三麻模型的小规模监督训练，双模型实时接口验收见 [策略模型设计](policy-model.md#双模型小规模训练与实时验收2026-10-13)。训练目标固定为当前可见局面到高段位玩家实际动作，不增加收益或价值预测目标。本文下方保留先前四麻采集与实验记录。

## 已获取数据

| 玩法 | 目标完整对局 | 实际完整对局 | 状态 |
| --- | ---: | ---: | --- |
| 雀魂四麻 | 50,000 | 50,000 | 已完成结构检查、UUID 与事件内容去重 |
| 雀魂三麻 | 50,000 | 0 | 未找到可直接取得的已验证公开完整 MJAI 包；公共索引请求返回 429 |

四麻共 528,449 个小局、53,608,412 条事件，压缩牌谱文件共 273,222,258 字节。2026 年 23,179 场，2021 年 26,821 场；两段年份分布存在明显间隔，后续评估应按年份另报结果。扫描的 50,006 份记录中，6 份因小局缺少结果而排除。完成计数不只检查 `end_game`；上游转换工具会追加这个标记。

数据来自 [nikketryhard/tenhou-houou-mjai](https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai/tree/6450bb584cef43ede3b514df48e301a832c6818b)，固定 revision `6450bb584cef43ede3b514df48e301a832c6818b`。本轮只选雀魂王座间文件，没有混入天凤牌谱。

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `majsoul-throne-2026.tar` | 170055680 | `86319ea7d42ff9ec6d877567ad83d1788c5840a49abaf672e6330d6132501f02` |
| `majsoul-throne-2021.tar` | 293683200 | `cc07362085ca44c2fd702e9bbfdcd9d66771be3704e201f55b1dbd21837b7073` |

“王座间”是发布者分类，未逐个核验玩家段位；MJAI 未保留官方操作列表和赛制头部。数据集许可标签为 `other`，不把转换工具许可当作原始牌谱再发布许可。

本地文件：

- `four-player/manifest.jsonl`：50,000 场源归档、成员名、UUID、三个内容哈希、事件与小局统计。
- `four-player/data/games/`：逐场 `.mjai.json.zst` 原始分片。
- `four-player/report.json`：结构审计与排除原因；不是逐事件规则正确性的证明。
- `collection-summary.json`：数量和整场训练划分。
- `research/source-findings.json`：三麻找源、索引返回状态和公开服务约束。

## 复现四麻入库

使用 Python 3.12 和 Node.js 18+。创建环境后，本文的 `python` 指激活环境中的 Python；采集和转换需要 MJAI 依赖，训练另需 PyTorch，启动 macOS 客户端需原生应用依赖。

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-mjai.txt -r requirements-training.txt -r requirements.txt
```

本机实测复用了 `/Users/kenny/Desktop/Maj-Soul-PlusPlus-model/.venv/bin/python`，没有修改其依赖。新副本没有自带 `.venv`。两个归档都可通过固定版本 URL 下载，断点续传由 curl 提供。现有 2026 归档也可直接复用。

```sh
mkdir -p .local/high-rank-50k/archives
for year in 2026 2021; do
  curl --fail --location --retry 3 --continue-at - \
    --output ".local/high-rank-50k/archives/majsoul-throne-${year}.tar" \
    "https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai/resolve/6450bb584cef43ede3b514df48e301a832c6818b/majsoul-throne-${year}.tar"
done
```

核对上述大小与 SHA256 后入库。相同命令再次运行会验证已存文件并继续，损坏的源文件不能混入已有结果。

```sh
python scripts/policy_corpus_audit.py \
  .local/high-rank-50k/archives/majsoul-throne-2026.tar \
  .local/high-rank-50k/archives/majsoul-throne-2021.tar \
  --players 4 --limit 50000 \
  --output .local/high-rank-50k/four-player \
  --source-url https://huggingface.co/datasets/nikketryhard/tenhou-houou-mjai/tree/6450bb584cef43ede3b514df48e301a832c6818b \
  --publisher-room throne
```

## 训练设计与隔离

该历史实验沿用 v1 的 756,545 参数候选动作评分网络，四麻和三麻分别训练和加载权重。输入只含本人手牌与当时公开局面；输出是在当前合法候选集合上的偏好概率。学习目标是模仿记录中的玩家选择，概率不是和牌率或胜率。

本轮没有因扩容重新分配既有 10,000 场的集合。新增 `policy_freeze_split.py --previous`，保留此前训练、验证和测试归属，验证来源哈希，并要求保留开发排除名单。50,000 场中，49 场此前已用于开发或对照验收，继续排除，因此正式可选集合为：

| 集合 | 完整对局数 |
| --- | ---: |
| 训练 | 39,961 |
| 验证 | 4,995 |
| 测试 | 4,995 |
| 开发排除 | 49 |

固定文件是 `.local/high-rank-50k/split.json`。同一场的全部座位与全部小局始终属于同一集合。此划分描述数据准备，不表示已经完成该规模训练。

小规模管线实验从正式训练集合中取 200 场，2021 和 2026 各 100 场。转换全部成功，得到 125,665 条样本；它自己的训练、验证、测试为 160 / 20 / 20 场，不接触正式验证或测试集合。权重、训练指标、动作覆盖与导出误差见 `models/four-player-pilot.report.json`。小规模实验只能验证训练和部署流程，不能作为正式留出集成绩或实战棋力结论。

本轮单次 CPU 训练 1 轮、耗时 147.48 秒，实际梯度更新使用 100,317 条训练样本。20 场小规模测试的首选一致率为 54.62%，前三候选一致率为 77.00%，出牌一致率为 45.61%；吃为 0/166、加杠为 0/9、大明杠为 0/2，不能只用整体准确率判断模型可用性。32 个导出校验窗口的首选全部一致，PyTorch / NumPy 最大绝对误差为 `5.96e-7`。权重 SHA256 是 `a5d6b4b7c529a0f181a9fe459a07ed803a61c57b485dbc79455a55b33e6feef4`。

全量转换和训练使用现有流式工具，以下是继续运行命令，并非已完成结果：

```sh
python scripts/policy_convert_mjai.py \
  --manifest .local/high-rank-50k/four-player/manifest.jsonl \
  --split .local/high-rank-50k/split.json \
  --output .local/high-rank-50k/training \
  --limit 49951 --workers 4

python scripts/policy_train_corpus.py \
  --manifest .local/high-rank-50k/training/manifest.jsonl \
  --split .local/high-rank-50k/split.json \
  --players 4 --epochs 1 --batch-size 128 --threads 2 --device cpu \
  --output .local/high-rank-50k/models/four-player-full.npz
```

转换器继续使用 `riichienv==0.4.10` 重建操作集合；缺少赛制原始证据时保持未知，发生杠后的剩余小局窗口仍排除。旧四麻语料的 19 场官方对照验收不能替代本次所有 50,000 场逐局验证。后续应先补赛制元数据及年份分层评估，再决定网络增大或强化学习，不因采集数量达到目标直接启用实战模型。

## 模型输出到游戏动作

当前源码已使用 `PolicyAdvisor → advisor worker → 客户端 advice → unity_actions → unity_transport`。模型返回完整候选参数，包括红牌、消耗牌、来源座位、手切／摸切与 `actionId`。执行入口重新验证当前局面与操作窗口，等待 RPC 确认和游戏动作回显；同一决策重复提交会拒绝。

新增 `tests/test_policy_unity_integration.py` 通过真实 NumPy 导出模型和真实 JavaScript 传输代码，使用内存连接验证 36 个动作案例，覆盖出牌、立直、吃、碰、三类杠、拔北、自摸、荣和、九种九牌和跳过，也验证过期局面、smoke 模型不发送。测试权重专门选择各合法动作，不用于评价训练棋力；未连接真实游戏服务器。

本轮新训练权重另在 4 场官方格式牌谱的 32 个真实出牌局面上通过同一协议验证，覆盖两个年份与全部四个座位。房间类别从相同 UUID 的牌谱头恢复，逐条确认补充前后模型特征、候选集合与输出概率完全一致。另一个缺少房间类别证据的重建状态被执行入口拒绝。报告在 `research/real-model-action-check.json`，可复现脚本在 `research/check-trained-actions.py`。真实权重检查只覆盖出牌；其他动作由上述确定性模型测试覆盖。模拟服务器确认不代表在线服务器已经接受这些动作。

加载模型前检查：

```sh
python scripts/policy_launch.py \
  --four-player .local/high-rank-50k/models/four-player-pilot.npz --check
```

显式启动源码客户端前需先退出已有 Maj-Soul++，然后去掉 `--check`。启动器只读检查单实例锁，若已有实例仍在运行会明确拒绝启动，因为已有进程不能读取这次新传入的模型路径；`--check` 会报告这一状态且不影响已有 App。三麻接口为 `--three-player /path/to/real-three-player.npz`；当前没有真实三麻权重可传入。运行时只需应用依赖与 NumPy，PyTorch 只用于训练。现有自动打牌开关默认关闭。本轮没有启动真实对局、替换桌面 App 或验证原生 WebKit 界面。

## 三麻剩余条件

本轮实际取得的雀魂三麻完整 MJAI 数量为 0。已找到的 66,514 场三麻 manifest 属于天凤，且没有公开牌谱本体，未用它替换雀魂数据。雀魂牌谱屋三麻索引的最小请求返回 429，未重试；维护者说明代码访问需要申请 API key，限 1 QPS，每页最多 150 条。即使有索引，也仍需取得完整牌谱再转换。

- [API key 与速率说明](https://github.com/SAPikachu/amae-koromo/issues/129#issuecomment-5867486883)
- [索引每页 150 条上限](https://github.com/SAPikachu/amae-koromo/issues/132#issuecomment-5613235588)
- [牌谱屋项目模式映射](https://github.com/SAPikachu/amae-koromo/blob/c14853b6e1f34c2ddbbf9c806211b8886f6e040e/src/data/types/gameMode.ts)：26 三王座南、24 三玉南；东场分别 25、23。

取得可用的雀魂三麻 MJAI 包或索引访问及完整牌谱导出渠道后可继续。结构入库现已支持 `--players 3`，拒绝第四座、吃、二至八万及非北拔北；它仍不等于三麻训练转换器已经完成。实测当前引擎支持 `kita`，但会静默忽略另一方言 `nukidora`，因此当前审计拒绝后一方言，保留明确失败。

三麻训练还需实现人数、牌山、拔北补牌与振听状态适配，并用真实官方原谱逐项对照。普通 MJAI `kita` 不足以确定手中已有北、刚摸到北时的手切／摸切选择；缺少原始 `moqie` 的歧义标签应排除，不能猜测。现有三麻模型动作接口及合成拔北测试不能计为真实三麻训练完成。
