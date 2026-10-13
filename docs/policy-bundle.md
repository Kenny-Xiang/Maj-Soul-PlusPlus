# 将全量监督模型装入 App

正式模型 App 在启动时自动读取资源目录 `policy-models/manifest.json`，校验权重 SHA256 后分别加载三麻与四麻模型。无需从终端设置模型路径。模型常驻内存，当前服务端操作窗口触发后台推理；现有候选校验、建议窗口校验、超时清理和执行确认保持生效。

训练目标固定为当前可见局面到高段位玩家实际动作的监督模仿。模型文件必须来自已完成全量训练和导出校验的报告；文件名含 `full` 不能作为训练完成的证据。

当前源码要求特征 v2（54 维全局输入）和 `majsoul-candidate-cnn-v2` 权重。v2 移除了赛制长度两列，仍保留场风、自风、公开宝牌、赤牌与三麻拔北信息；v1 权重不兼容，必须在独立输出目录重新训练并评估。下列路径仅为命令示例，实际打包须指向本轮已验证的两套 v2 模型；历史 v1 模型与已安装 App 不会自动迁移或替换。

## 准备模型资源

在独立构建目录操作，并先完成两套模型。以下命令不会启动游戏或替换已安装 App：

```sh
POLICY_PYTHON=/Users/kenny/Desktop/Maj-Soul-PlusPlus-model/.venv/bin/python

"$POLICY_PYTHON" scripts/policy_prepare_bundle.py \
  --three-player .local/high-rank-50k/models/three-player-full.npz \
  --four-player .local/high-rank-50k/models/four-player-full.npz \
  --minimum-games 40000 \
  --output build/policy-models
```

该脚本读取每个 NPZ 旁边同名的 `.report.json`，并检查：

- 三麻和四麻槽位、`behavior-cloning` 目的及特征／动作版本匹配。
- 模型内训练报告与外部报告一致，外部报告的模型 SHA256 匹配文件。
- `selectedGames == manifestGames`，未设置 `maxGames`，使用冻结的完整牌局切分。
- 每套至少 40,000 场，训练／验证／测试集合非空且没有交叉。这个下限容纳原始 50,000 场中的开发集与质量筛选剔除；实际训练场数仍写入清单，不等同于宣称训练了 50,000 场。
- 最终模型导出校验通过。小规模 pilot、smoke 和未完成的 checkpoint 无法作为全量模型打包。

输出包含两套权重、两份完整训练报告和清单。清单记录模型、报告、输入样本清单和冻结切分的哈希，打包时再次校验。

## 构建与核对

```sh
MAJSOUL_BUILD_PYTHON="$POLICY_PYTHON" \
MAJSOUL_POLICY_BUNDLE="$PWD/build/policy-models" \
  scripts/build.sh
```

构建 Python 需要同时安装 `requirements-build.txt` 与 `requirements-policy.txt`；打包后的运行时仅需 NumPy，不包含训练所需的 PyTorch。产物位于 `dist/Maj-Soul++.app`。构建成功后应核对包内 `policy-models/manifest.json`、两套 NPZ 哈希、应用签名以及随包源代码，再决定安装。

直接运行冻结应用的离线验收入口：

```sh
"dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++" --verify-policy
```

该入口忽略模型路径环境变量，强制加载包内两套实际权重。在固定可见局面上检查玩法槽位和 SHA256、完整合法候选及参数、首选动作、概率有限且归一，以及等待窗口不出建议；覆盖 17 条操作流程的 56 个窗口和全部 12 类候选动作。成功输出 `status: ok` 的 JSON，失败返回非零退出码。它不启动 GUI、不连接游戏、不读写游戏 profile，也不运行 Node 或 PyTorch；因此该验收不代表在线牌局、WebKit 显示和长时间后台运行已经验证。

不设置 `MAJSOUL_POLICY_BUNDLE` 的普通构建保持原有规则推荐器。设置了该变量但资源校验失败，构建立即失败。现有 Python 路径仍默认 `.venv/bin/python`；`MAJSOUL_BUILD_PYTHON` 仅用于显式选用另一个构建环境。

## 运行时行为

- App 存在模型资源目录时，缺清单、缺权重、哈希错误、玩法或版本不匹配都会显示“策略模型未能加载”，不会悄悄回退到其他模型或规则推荐器。
- `MAJSOUL_POLICY_MODEL_3P` 和 `MAJSOUL_POLICY_MODEL_4P` 可分别覆盖包内对应槽位，适合明确指定模型的开发验证；单独覆盖一个槽位时，另一个仍读取包内模型。两者都显式指定时可替代损坏的包内资源。
- 未配置的玩法显示“当前玩法没有配置策略模型”，不会使用另一玩法的权重。
- 启动日志记录已加载的两套模型 SHA256；每条策略建议继续携带实际使用的 `modelSha256`，可与打包清单追溯比对。
- 自动执行仍按现有 App 的用户开关控制，模型加载本身不启用自动执行。

源代码运行仍可使用显式检查，不会打开 GUI：

```sh
"$POLICY_PYTHON" scripts/policy_launch.py \
  --three-player .local/high-rank-50k/models/three-player-full.npz \
  --four-player .local/high-rank-50k/models/four-player-full.npz \
  --check
```
