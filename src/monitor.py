#!/usr/bin/env python3
"""Maj-Soul++: Mahjong Soul window with a live statistics overlay and local logs."""
import json
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / "Library/Application Support/Maj-Soul++"


def collector_source():
    core = (ROOT / "core.cjs").read_text(encoding="utf-8")
    browser = (ROOT / "browser.js").read_text(encoding="utf-8")
    return ("(function(discover){'use strict';const core=(()=>{const module={exports:{}};\n"
            + core + "\nreturn module.exports;})();\n" + browser + "\n})(null);")


def overlay_update(event):
    from terminal_stats import format_turn
    if event["kind"] == "turn" and event['state']['phase'] == 'ended':
        packet = {"kind": "status", "phase": "ended", "reset": True,
                  "text": "对局已结束，统计已重置 · 等待下一场"}
    elif event["kind"] == "turn":
        packet = {"kind": "turn", "text": format_turn(event)}
    elif event["kind"] in ("status", "error"):
        phase = event.get("phase")
        labels = {"waiting": "等待对局 · 发牌及场上动作后自动更新", "connected": "已连接牌局 · 等待最新统计",
                  "playing": "对局进行中 · 等待最新统计", "between_rounds": "小局结束 · 以下为最新统计",
                  "ended": "对局已结束，统计已重置 · 等待下一场", "disconnected": "连接中断 · 以下统计可能已过时"}
        packet = {"kind": "status", "phase": phase,
                  "reset": bool(event.get('reset')),
                  "text": event.get("message", "统计暂不可用") if event["kind"] == "error" else labels.get(phase, "等待最新统计")}
    else:
        return None
    return "window.__mjStatsOverlay?.update(" + json.dumps(packet, ensure_ascii=False) + ");"


def main():
    if sys.platform != "darwin":
        raise SystemExit("此程序使用 macOS 系统 WebKit，请在 Mac 上运行。")
    try:
        import WebKit
    except ImportError:
        local_python = ROOT.parent / ".venv/bin/python"
        if local_python.exists() and Path(sys.prefix) != ROOT.parent / ".venv":
            os.execv(str(local_python), [str(local_python), str(Path(__file__).resolve()), *sys.argv[1:]])
        raise SystemExit("缺少开发依赖；正常使用请打开「Maj-Soul++.app」。")

    import AppKit
    import fcntl
    from Foundation import NSObject, NSURL, NSURLRequest, NSUUID, NSTimer
    from terminal_stats import TerminalLog

    # A named persistent WebKit profile keeps this window's login separate from Safari.
    profile_id = "382523D9-074A-4A9B-8FA4-1BC45E1EDCE7"
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    local = DATA
    local.mkdir(parents=True, exist_ok=True)
    # Keep diagnostics available without a Terminal window, including frozen builds.
    sys.stdout = sys.stderr = (local / "launcher.log").open("a", buffering=1)
    with open(os.devnull, "rb") as null:
        os.dup2(null.fileno(), 0)
    os.dup2(sys.stderr.fileno(), 1)
    os.dup2(sys.stderr.fileno(), 2)
    lock = (local / "monitor.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.seek(0)
        owner = lock.read().strip()
        if owner.isdigit():
            existing = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(owner))
            if existing:
                existing.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        return
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    log = TerminalLog(local / "logs")
    (local / "current-log-path").write_text(str(log.text_path), encoding="utf-8")
    log.write("Maj-Soul++ · 开局发牌及每个场上动作后更新浮层")
    log.write("正在打开独立游戏窗口；采集器自动安装。首次请在新窗口登录。")
    log.write(f"文本记录：{log.text_path}\n结构化记录：{log.json_path}")

    class Delegate(NSObject):
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            origin = message.frameInfo().securityOrigin()
            if not message.frameInfo().isMainFrame() or str(origin.protocol()) != "https" or str(origin.host()) != "game.maj-soul.com":
                return
            try:
                event = json.loads(str(message.body()))
                log.accept(event)
                update = overlay_update(event)
                if update:
                    message.webView().evaluateJavaScript_completionHandler_(update, None)
            except Exception as error:
                print(f"[记录失败] {error}", file=sys.stderr, flush=True)

        def webView_didFailProvisionalNavigation_withError_(self, view, navigation, error):
            if error.code() != -999:
                log.write(f"[页面加载失败] {error.localizedDescription()}")

        def webViewWebContentProcessDidTerminate_(self, view):
            log.write("[页面进程已退出] 监听中断，请关闭窗口后重新启动程序。")

        def windowWillClose_(self, notification):
            if notification.object() is window:
                log.write("游戏窗口已关闭，监测结束。")
                app.terminate_(None)

        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, view, config, action, features):
            # Login providers can open a separate window; reuse WebKit's supplied configuration.
            popup, popup_view = make_window(config, "Maj-Soul++ 登录")
            self.popups.append((popup, popup_view))
            return popup_view

        def webViewDidClose_(self, view):
            for popup, popup_view in self.popups:
                if popup_view is view:
                    popup.close()
                    break

    delegate = Delegate.alloc().init()
    delegate.popups = []

    def make_window(config, title):
        style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
                 | AppKit.NSWindowStyleMaskMiniaturizable | AppKit.NSWindowStyleMaskResizable)
        rect = AppKit.NSMakeRect(0, 0, 1200, 760)
        result = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False)
        result.setReleasedWhenClosed_(False)
        result.setTitle_(title)
        result.setDelegate_(delegate)
        view = WebKit.WKWebView.alloc().initWithFrame_configuration_(rect, config)
        view.setNavigationDelegate_(delegate)
        view.setUIDelegate_(delegate)
        view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        result.setContentView_(view)
        result.center()
        result.makeKeyAndOrderFront_(None)
        return result, view

    menu = AppKit.NSMenu.alloc().init()
    for title, items in [
        ("Maj-Soul++", [("退出 Maj-Soul++", "terminate:", "q")]),
        ("编辑", [("撤销", "undo:", "z"), ("剪切", "cut:", "x"),
                ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")]),
        ("窗口", [("最小化", "performMiniaturize:", "m"), ("关闭", "performClose:", "w")]),
    ]:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        submenu = AppKit.NSMenu.alloc().initWithTitle_(title)
        for label, selector, key in items:
            submenu.addItemWithTitle_action_keyEquivalent_(label, selector, key)
        item.setSubmenu_(submenu)
        menu.addItem_(item)
    app.setMainMenu_(menu)

    config = WebKit.WKWebViewConfiguration.alloc().init()
    profile = WebKit.WKWebsiteDataStore.dataStoreForIdentifier_(NSUUID.alloc().initWithUUIDString_(profile_id))
    config.setWebsiteDataStore_(profile)
    config.setMediaTypesRequiringUserActionForPlayback_(WebKit.WKAudiovisualMediaTypeNone)
    controller = config.userContentController()
    controller.addScriptMessageHandler_name_(delegate, "mjStatistics")
    script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        collector_source(), WebKit.WKUserScriptInjectionTimeAtDocumentStart, True)
    controller.addUserScript_(WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        (ROOT / "overlay.js").read_text(encoding="utf-8"), WebKit.WKUserScriptInjectionTimeAtDocumentStart, True))
    controller.addUserScript_(script)
    window, view = make_window(config, "Maj-Soul++")
    view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_("https://game.maj-soul.com/1/")))
    app.activateIgnoringOtherApps_(True)
    # Give Python a periodic callback so terminal signals also work while AppKit is idle.
    timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.5, True, lambda timer: None)
    signal.signal(signal.SIGINT, lambda signum, frame: app.terminate_(None))
    signal.signal(signal.SIGTERM, lambda signum, frame: app.terminate_(None))
    app.run()
    timer.invalidate()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("--verify-native", "--verify-overlay"):
        # Exercise the packaged runtime offline, without touching the game profile.
        import runpy
        test_root = ROOT / "source/tests" if getattr(sys, "frozen", False) else ROOT.parent / "tests"
        runpy.run_path(str(test_root / ("test_native.py" if sys.argv[1] == "--verify-native" else "test_overlay.py")), run_name="__main__")
    else:
        main()
