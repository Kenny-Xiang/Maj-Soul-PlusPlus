# Maj-Soul++

**简体中文** | [English](README.en.md)

面向雀魂国服的 macOS 客户端，基于系统 WebKit，提供实时牌局统计、半透明浮层和行动建议。应用界面以中文显示。

## 功能

- **牌局统计**：展示本人手牌、场局、点数、剩余牌数、宝牌指示牌、各家牌河与副露、拔北及已确认立直状态。
- **统计浮层**：双栏布局随窗口调整，除顶部自动打牌按钮外支持鼠标点击穿透；收到牌桌动作后自动更新。
- **行动建议**：依据本人手牌、公开信息和服务端允许的操作，比较弃牌、鸣牌、立直、拔北、九种九牌及跳过；可自摸或荣和时优先提示。
- **自动打牌**：浮层开关默认关闭，支持四麻（默认）和三麻，以及东风（默认）和南风。使用当前 Unity 客户端的已登录连接，按对应段位和所选场次的金币门槛选择普通段位房间，自动匹配、按建议操作并继续下一场。按动作和局面调整等待节奏，配合小幅随机变化，临近截止时优先提交。每次操作核对服务器回执与牌局动作；重连期间保留开关，可信状态恢复后自动继续，真实数据或操作异常时暂停。详见[使用说明](docs/使用说明.md#自动打牌)。
- **手牌分析与记录**：等待行动时显示向听、有效未见牌和手牌估值；在本地保存文本与 JSONL 日志。

## 快速开始

支持 **Apple Silicon Mac、macOS 14 及以上版本**。

已有 `Maj-Soul++.app` 时，直接打开并在游戏窗口内登录。应用包含 Python 与运行依赖，可独立运行；后续启动可复用有效登录，再次打开会激活已有窗口。详见[使用说明](docs/使用说明.md)。

从源码运行需要 **Python 3.12**；执行测试另需 **Node.js 18 及以上版本**。

```sh
git clone https://github.com/Kenny-Xiang/Maj-Soul-PlusPlus.git
cd Maj-Soul-PlusPlus
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python src/monitor.py
```

依赖版本由 [requirements.txt](requirements.txt) 和 [requirements-build.txt](requirements-build.txt) 固定。采集脚本在页面加载前自动安装，无需手动注入。

## 测试与构建

以下命令均在仓库根目录、完成上述环境配置后执行。

```sh
# 运行完整测试
./scripts/test.sh

# 构建并打开独立应用
./scripts/build.sh
open 'dist/Maj-Soul++.app'
```

测试涵盖协议与状态、日志、行动建议、后台任务、原生 WebKit 回放及浮层布局。原生检查需要有效的 macOS 图形会话，使用本地样本，不连接游戏服务器。算法版本对比见[离线评估说明](docs/advisor-evaluation.md)（英文）。

构建输出位于 `dist/Maj-Soul++.app`，不会替换其他位置的应用。更新已安装应用需重新构建并替换；推送源码不会自动更新应用。

验证打包后的运行环境：

```sh
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-native
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-overlay
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-advisor
```

## 数据与限制

运行日志保存在 `~/Library/Application Support/Maj-Soul++/`：`logs/` 存放文本与 JSONL 记录，`launcher.log` 存放诊断信息。WebKit 登录数据独立于其他浏览器；运行数据不写入源码目录或应用包。

- **信息范围**：仅使用当前窗口收到的信息，不读取对手暗手。已知牌计数不等于剩余牌山分布；中途加入能否恢复完整状态取决于服务端数据。
- **建议有效性**：缺少可信基线、恢复尚未验证、连接断开或小局结束时暂停分析；局面变化或提交操作后撤销旧建议。
- **模型范围**：面向普通三麻、四麻规则，不涵盖自定义规则或活动模式。概率与打点包含未经实战校准的估计，不保证最优决策；离线测试不代表所有真实对局场景均已验证。

指标定义、计算方法与模型假设见[行动建议文档](docs/出牌建议.md)。

## 文档

除离线评估说明外，以下文档以中文编写。

- [使用说明](docs/使用说明.md)
- [行动建议：指标、模型与限制](docs/出牌建议.md)
- [消息监听与牌局信息完整性](docs/监听方法与完整对局信息获取分析.md)
- [雀魂规则参考](docs/雀魂规则_Agent参考.md)
- [离线评估说明（英文）](docs/advisor-evaluation.md)

`mahjong` 依赖许可证见 [mahjong-LICENSE.txt](docs/mahjong-LICENSE.txt)。

## 参与开发

源码、测试与文档分别位于 `src/`、`tests/` 和 `docs/`。请在功能分支上修改，运行相关检查后向 `main` 提交 Pull Request；提交说明、PR 标题与正文使用英文。环境、日志及构建产物不纳入 Git。
