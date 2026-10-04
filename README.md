# Maj-Soul++

macOS 雀魂独立游戏窗口：通过 WebKit 原生消息通道接收当前页面的对局消息，在窗口上半区显示半透明统计。每小局发牌后立即刷新，此后随所有玩家的场上动作刷新；整场结束后清空当前统计。无需本机 HTTP 服务或证书设置。

普通使用直接打开桌面的 `Maj-Soul++.app`。本目录是可以独立测试、重新构建并使用本地 Git 跟踪的源码工程。

## 目录

```text
Maj-Soul++/
├── src/                       当前应用源码
│   ├── monitor.py             macOS 窗口、原生消息桥接和启动逻辑
│   ├── terminal_stats.py      统计格式化与本地日志（不打印终端）
│   ├── core.cjs               协议解码与对局状态
│   ├── browser.js             被动监听、动作更新与结束重置
│   └── overlay.js             半透明、鼠标穿透浮层
├── tests/                     JavaScript、Python 和原生 WebKit 测试
│   └── fixtures/              固定回放样本
├── legacy/                    旧方案参考及回归测试所需文件
├── docs/                      使用说明、方法分析和规则参考
│   └── verification/          历史验证证据
├── scripts/test.sh            运行完整测试
├── scripts/build.sh           构建独立 App
├── requirements.txt           运行依赖
├── requirements-build.txt     构建依赖
├── Maj-Soul++.spec             PyInstaller 构建配置
└── .gitignore                 排除环境、日志、缓存及构建产物
```

## 开发环境

当前构建目标为 Apple Silicon Mac、macOS 14 及以上。使用独立安装的 **Python 3.12**，不要用 Xcode 自带的旧 Python；JavaScript 测试和旧方案脚本生成需要 **Node.js 18+**。运行依赖固定为 PyObjC 11.1，打包工具固定为 PyInstaller 6.22.0。

在工程目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
```

本机交付目录已经准备好被 Git 忽略的 `.venv`，可以直接执行后面的测试和构建命令；在另一台机器或新克隆目录中需先完成上面的环境准备。

## 运行、测试与构建

源码运行：

```sh
.venv/bin/python src/monitor.py
```

完整测试：

```sh
./scripts/test.sh
```

测试依次执行 JavaScript 状态/监听检查、Python 格式化/日志检查、真实 WebKit 的隔离回放及浮层布局检查。后两项需要当前用户的 macOS 图形会话，只加载本地样本，使用非持久网站数据配置，不连接游戏服务器或操作正在玩的对局。

构建独立 App：

```sh
./scripts/build.sh
open 'dist/Maj-Soul++.app'
```

产物为 `dist/Maj-Soul++.app`，内含 Python、依赖、采集脚本、文档和本工程源码；运行时不依赖本源码目录、外部 Python、Node.js 或 Xcode。构建只写入本工程 `build/` 和 `dist/`，不会覆盖桌面正在使用的 App。

验证打包后的运行环境：

```sh
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-native
'dist/Maj-Soul++.app/Contents/MacOS/Maj-Soul++' --verify-overlay
```

以上入口同样使用离线样本。需要保存浮层预览时，在源码目录运行 `PYTHONPATH=src .venv/bin/python tests/test_overlay.py --snapshot`，图片输出到被 Git 忽略的 `build/overlay-preview.png`。

## 数据与版本管理

运行日志、诊断文件及单实例锁位于 `~/Library/Application Support/Maj-Soul++/`。网页登录状态由系统 WebKit 保存在用户目录，不放入工程。重复启动会唤起已有游戏窗口。

Git 跟踪源码、测试样本、文档、依赖清单及构建配置；`.gitignore` 排除 `.venv`、日志、证书、缓存、生成的监听脚本、`.app` 和打包产物。旧完整桌面备份保留在已安装 App 中，不复制进源码工程。仓库使用 `main` 分支，公开托管于 [Kenny-Xiang/Maj-Soul-PlusPlus](https://github.com/Kenny-Xiang/Maj-Soul-PlusPlus)。应用与工程的显示名称保持为 Maj-Soul++。

```sh
git status
git diff
git log --oneline
```

## 说明与限制

完整使用方法见 [使用说明](docs/使用说明.md)，监听及中途接入的边界见 [方法分析](docs/监听方法与完整对局信息获取分析.md)。历史记录中的旧文件路径和名称按原样保留，不代表当前工程结构。

本次目录整理后的复验结果见 [工程整理验证记录](docs/verification/工程整理验证.json)：16 项 JavaScript、4 项 Python、原生 WebKit 回放、浮层检查，以及重新打包后的两个离线验证入口均已通过。

监听只读取当前独立窗口能收到的消息。中途进入牌局时，信息完整性取决于服务器提供的恢复数据；不会补出对手未公开手牌，也不保证恢复开始监听前的全部历史。已知牌计数不等于剩余牌山的精确分布。
