# Maj-Soul++

**简体中文** | [English](README.en.md)

为雀魂提供独立 macOS 游戏窗口，支持实时记牌、半透明统计浮层，以及根据本人手牌、公开牌局信息和服务端允许的操作生成行动建议。

应用使用系统 WebKit 引擎加载游戏，监听该窗口收到的消息，并通过原生消息桥将统计信息传递给 Python。开局发牌及每个被接受的牌桌动作都会触发浮层更新，包括其他玩家的动作。

源代码仓库：[Kenny-Xiang/Maj-Soul-PlusPlus](https://github.com/Kenny-Xiang/Maj-Soul-PlusPlus)。应用界面和详细参考文档目前使用中文。

## 功能

- **固定双栏浮层：** 左侧显示牌局信息，右侧显示记录状态、诊断信息和当前行动建议。浮层位于窗口上半部分，鼠标点击可以穿透到游戏。
- **实时牌局统计：** 本人手牌与座位、场局信息、各家点数、剩余牌数、宝牌指示牌、各家牌河与副露、拔北数量，以及已知牌计数。
- **已确认立直标记：** 对手名称旁标记已确认的立直或两立直状态。仅有立直宣言时不会视为已确认；新一局开始或整场对局结束时清除标记。
- **行动建议：** 在存在合法操作窗口且所需信息完整时，比较服务端允许的弃牌、吃、碰、三种杠、立直、拔北、九种九牌流局和跳过操作。吃碰建议会列出所用牌及后续合法弃牌；可以自摸或荣和时优先提示和牌。应用只展示建议，不代替玩家执行操作。
- **行动间的手牌分析：** 手牌变化后重新评估。在没有合法操作窗口时，展示当前向听数、有效未见牌和手牌估值，等待下一次行动；此时不展示可立即执行的弃牌及其放铳风险。
- **明确的更新边界：** 重复动作不会重复更新。小局之间保留统计，整场结束时清空显示，历史日志继续保留。
- **本地运行：** 使用独立的 WebKit 登录数据，同时只运行一个游戏窗口，并将文本与 JSONL 日志保存在用户数据目录中。

推荐算法按雀魂普通三麻或四麻规则进行估算。概率来自未经实战校准的公开信息模型，不是实测胜率，也不保证最优决策。模型、指标和限制详见[行动建议文档](docs/出牌建议.md)。

## 使用应用

打开 `Maj-Soul++.app`，首次使用时在游戏窗口内登录。应用保存独立的 WebKit 网站数据，后续启动可以复用仍有效的登录状态。再次启动时会激活已有窗口。关闭主窗口或退出应用即可结束运行。

构建后的应用包含 Python、依赖和应用资源，可脱离源码目录独立运行，无需额外安装 Python、Node.js 或 Xcode。从源码构建的方法见下文。

## 开发环境要求

- Apple Silicon Mac，运行 macOS 14 或更新版本。
- 独立安装的 **Python 3.12**。
- **Node.js 18 或更新版本**，用于运行 JavaScript 测试。

运行依赖固定在 `requirements.txt` 中：PyObjC 11.1 和 `mahjong` 2.0.0。构建依赖列在 `requirements-build.txt` 中，包括 PyInstaller 6.22.0。

在仓库根目录创建独立环境并安装依赖：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
```

## 从源码运行

```sh
.venv/bin/python src/monitor.py
```

采集脚本会在游戏页面加载前安装，无需手动注入。

## 测试

运行完整测试：

```sh
./scripts/test.sh
```

脚本依次运行 JavaScript 协议与状态检查、Python 格式化与日志检查、推荐算法及后台线程测试、隔离的原生 WebKit 回放，以及浮层布局检查。

原生 WebKit 和浮层检查需要有效的 macOS 图形会话。它们使用本地固定样本和非持久化 WebKit 数据存储，不连接游戏服务器，也不操作真实对局。

使用 `scripts/advisor_compare.py` 可在固定离线状态上比较推荐算法版本；样本、评分分项、耗时统计及验证边界见[离线评估说明](docs/advisor-evaluation.md)。

保存本地浮层预览：

```sh
PYTHONPATH=src .venv/bin/python tests/test_overlay.py --snapshot
```

图片输出到 `build/overlay-preview.png`，该文件由 Git 忽略。

## 构建独立应用

```sh
./scripts/build.sh
open 'dist/Maj-Soul++.app'
```

构建产物为 `dist/Maj-Soul++.app`。PyInstaller 使用 `onedir` 和 `windowed` 模式，将 Python 运行时、依赖、采集脚本、文档和源码打包为不带控制台窗口的 macOS 应用。

构建过程写入仓库内的 `build/` 和 `dist/` 目录，不会替换其他位置已经安装的应用。更新应用时应修改源码后重新构建，不要直接编辑已签名的应用包。

使用离线入口验证打包后的运行环境：

```sh
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-native
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-overlay
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-advisor
```

## 仓库结构

```text
Maj-Soul-PlusPlus/
├── src/
│   ├── monitor.py             macOS 窗口、原生消息桥与启动入口
│   ├── terminal_stats.py      统计格式化与本地日志，不输出到控制台
│   ├── core.cjs               协议解码与牌局状态
│   ├── browser.js             被动采集、动作更新与整场重置
│   ├── overlay.js             支持点击穿透的半透明浮层
│   ├── advisor.py             牌理计算与合法行动评估
│   └── advice_worker.py       后台评估与过期结果失效处理
├── tests/                     JavaScript、Python 和原生 WebKit 测试
│   └── fixtures/              已录制的回放样本
├── docs/                      使用说明、协议分析和规则参考
├── README.md                  中文项目说明（默认）
├── README.en.md               英文项目说明
├── scripts/test.sh            完整测试入口
├── scripts/build.sh           独立应用构建入口
├── requirements.txt           运行依赖
├── requirements-build.txt     构建依赖
├── Maj-Soul++.spec            PyInstaller 配置
└── .gitignore                 忽略环境、运行数据和构建产物
```

## 本地数据

运行文件保存在：

```text
~/Library/Application Support/Maj-Soul++/
```

- `logs/`：每次运行的文本（`.txt`）与结构化（`.jsonl`）记录。
- `launcher.log`：启动与运行诊断信息。
- `monitor.lock`：单实例锁。

WebKit 将登录数据保存在用户配置中，不写入仓库。统计日志在后台写入，显示的时间戳使用北京时间（UTC+8）。运行数据不会写回应用包。

## 信息边界

采集器只能看到当前游戏窗口收到的消息。开局发牌可以建立完整基线；中途加入则取决于服务端提供的恢复数据。遇到动作缺失、未知动作、状态不一致或尚未验证的恢复边界时，会明确报告，不会将其显示为完整历史。

应用不推断对手暗手，也不重建从未收到的信息。已知牌计数会合并赤五与普通五，并避免将被鸣走的弃牌在副露中重复计数。它不代表剩余活牌山的准确组成：未见牌也可能位于对手手中或王牌中。

缺少所需基线、恢复尚未验证、连接断开或小局结束时，分析会暂停。新动作和已提交的操作会使旧建议失效，下一个合法操作窗口由服务端消息确定。自定义房间规则和活动模式不在推荐算法的普通规则假设范围内。

行动评分综合手牌估值、和牌机会、牌效率与风险。杠和拔北按未知补牌的可能结果加权，估计抢杠或抢北风险及新杠宝牌的不确定性，不会将某张未知补牌当作确定的后续弃牌。模型比较当前行动及必要的下一次摸牌或弃牌，不会穷举未来的行动序列、对手打法或最终顺位。

离线回放只验证固定样本中的行为，不能证明所有服务端恢复场景和真实对局边界情况都已经得到验证。

## 参与开发

在功能分支上修改代码，运行相关检查，并向 `main` 提交 Pull Request。提交说明、PR 标题和 PR 正文统一使用英文。源码修改与应用构建是两个独立步骤：向 GitHub 推送代码不会自动更新已安装的应用。

Git 跟踪源码、测试、固定样本、文档、依赖清单和构建配置。虚拟环境、运行数据、缓存、生成的应用包和构建产物由 `.gitignore` 排除。

## 更多文档

以下详细文档目前均为中文：

- [使用说明](docs/使用说明.md)
- [行动建议：指标、模型与限制](docs/出牌建议.md)
- [消息监听与牌局信息完整性分析](docs/监听方法与完整对局信息获取分析.md)
- [雀魂规则参考](docs/雀魂规则_Agent参考.md)

随应用打包的 `mahjong` 依赖许可证见 [mahjong-LICENSE.txt](docs/mahjong-LICENSE.txt)。
