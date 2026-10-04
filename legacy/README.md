# 旧方案参考

这些文件保留此前的浏览器检查器、终端和 HTTP 中转实现。当前 Maj-Soul++ 使用 `src/monitor.py` 中的原生 WebKit 通道，不运行这些启动器或中转服务。

- `build.cjs` 从当前 `src/core.cjs` 和 `src/browser.js` 生成 `安装终端监听.js`，供旧方案及回归测试使用。生成文件不提交 Git。
- `terminal.cjs`、`relay.html`、`relay.js` 是旧终端中转方案。
- `legacy-launch.sh`、`legacy-launcher.m` 是旧桌面启动器的原始备份，包含当时的目录假设，不作为当前入口使用。

正常开发、测试和打包请按根目录 README 操作。旧完整目录压缩备份仍保存在桌面已安装 App 的 `Contents/Resources/archive` 中，不放入源码仓库。
