#!/usr/bin/env python3
"""Maj-Soul++: Mahjong Soul window with a live statistics overlay and local logs."""
import json
import os
from pathlib import Path
import signal
import sys
import time

from autoplay_recovery import AutoplayRecovery

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / "Library/Application Support/Maj-Soul++"


class BackgroundActivity:
    """Keep user-enabled automation active; restore native policies when it ends."""
    def __init__(self, process, options, active_policy, write):
        self.process, self.options, self.active_policy, self.write = process, options, active_policy, write
        self.token = self.preferences = self.previous_policy = None
        self.session = None
        self.retired_sessions = set()
        self.accepting = True
        self.navigation = self.resume_request = None
        self.pulse_request = None
        self.last_pulse = float('-inf')
        self.pulse_error = None

    def update(self, view, session, enabled):
        if not self.accepting or not isinstance(session, str) or not session or type(enabled) is not bool:
            return
        if session in self.retired_sessions:
            return
        self.resume_request = None
        if session != self.session:
            if self.session is not None:
                self.release()
                self.retired_sessions.add(self.session)
            self.session = session
        if not enabled:
            self.release()
            return
        if self.token is not None:
            return
        self.token = self.process.beginActivityWithOptions_reason_(self.options, "Maj-Soul++ 自动打牌")
        preferences = view.configuration().preferences()
        policy_enabled = False
        if (self.active_policy is not None and hasattr(preferences, "inactiveSchedulingPolicy") and
                hasattr(preferences, "setInactiveSchedulingPolicy_")):
            try:
                self.previous_policy = preferences.inactiveSchedulingPolicy()
                self.preferences = preferences
                preferences.setInactiveSchedulingPolicy_(self.active_policy)
                policy_enabled = True
            except Exception as error:
                self.write(f"[后台活动] WebKit 调度策略设置失败：{error}")
        self.write("[后台活动] 已启用原生活动；允许锁屏和显示器休眠；" +
                   ("WebKit 非活跃调度设为正常" if policy_enabled else "WebKit 非活跃调度策略不可用"))

    def release(self):
        token, preferences, previous = self.token, self.preferences, self.previous_policy
        self.token = self.preferences = self.previous_policy = None
        self.pulse_request = None
        self.last_pulse = float('-inf')
        self.pulse_error = None
        try:
            if preferences is not None:
                preferences.setInactiveSchedulingPolicy_(previous)
        except Exception as error:
            self.write(f"[后台活动] WebKit 调度策略还原失败：{error}")
        finally:
            if token is not None:
                self.process.endActivity_(token)
                self.write("[后台活动] 已结束原生活动")

    def reset_page(self):
        self.accepting = False
        self.navigation = self.resume_request = None
        if self.session is not None:
            self.retired_sessions.add(self.session)
        self.session = None
        self.release()

    def navigation_started(self, navigation, preserve_activity=False):
        self.navigation = navigation
        self.resume_request = self.pulse_request = None
        self.accepting = False
        if not preserve_activity:
            self.release()

    def page_committed(self, navigation=None, preserve_activity=False):
        if navigation != self.navigation:
            return
        if preserve_activity:
            if self.session is not None:
                self.retired_sessions.add(self.session)
            self.session = self.navigation = self.resume_request = self.pulse_request = None
        else:
            self.reset_page()
        self.accepting = True

    def navigation_failed(self, view, navigation, resume_activity=True):
        if navigation != self.navigation:
            return
        self.navigation = None
        self.accepting = True
        if not resume_activity:
            self.resume_request = None
            return
        request = self.resume_request = object()
        session = self.session

        def completed(enabled, error):
            if self.resume_request is not request or self.session != session:
                return
            self.resume_request = None
            if error is not None:
                self.write(f"[后台活动] 导航结束后无法确认自动状态：{error}")
            else:
                self.update(view, session, enabled is True)

        try:
            view.evaluateJavaScript_completionHandler_(
                "location.protocol === 'https:' && location.hostname === 'game.maj-soul.com' && "
                "window.__mjAutoplay?.getStatus().enabled === true;", completed)
        except Exception as error:
            completed(None, error)

    def pulse(self, view, now, occluded):
        if (not self.accepting or self.token is None or not occluded or
                self.pulse_request is not None or now - self.last_pulse < .25):
            return
        request = self.pulse_request = object()
        self.last_pulse = now

        def completed(result, error):
            if self.pulse_request is not request:
                return
            self.pulse_request = None
            message = str(error) if error is not None else None
            if message and message != self.pulse_error:
                self.write(f"[后台活动] 后台调度未送达：{message}")
            self.pulse_error = message

        try:
            view.evaluateJavaScript_completionHandler_("window.__mjBackground?.pulse();", completed)
        except Exception as error:
            completed(None, error)


def collector_source():
    core = (ROOT / "core.cjs").read_text(encoding="utf-8")
    browser = (ROOT / "browser.js").read_text(encoding="utf-8")
    transport = (ROOT / "unity_transport.js").read_text(encoding="utf-8")
    return ("(function(){'use strict';const core=(()=>{const module={exports:{}};\n"
            + core + "\nreturn module.exports;})();\n" + transport + "\n" + browser + "\n})();")


def overlay_update(event):
    from terminal_stats import format_turn
    if event["kind"] == "turn" and event['state']['phase'] == 'ended':
        packet = {"kind": "status", "phase": "ended", "reset": True,
                  "text": "对局已结束，统计已重置 · 等待下一场"}
    elif event["kind"] == "turn":
        packet = {"kind": "turn", "text": format_turn(event),
                  "adviceKey": f"{event['session']}:{event['serial']}",
                  "advice": event.get("advice", {"status": "computing", "message": "正在评估当前牌局…"})}
    elif event["kind"] == "advice":
        packet = {"kind": "advice", "adviceKey": event["adviceKey"], "advice": event["advice"]}
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
    payload = json.dumps(packet, ensure_ascii=False)
    script = "window.__mjStatsOverlay?.update(" + payload + ");"
    if packet['kind'] == 'advice':
        script += "window.__mjAutoplay?.onAdvice(" + payload + ");"
    return script


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
    from Foundation import (NSObject, NSURL, NSURLRequest, NSUUID, NSTimer, NSProcessInfo,
                            NSActivityUserInitiatedAllowingIdleSystemSleep, NSActivityIdleSystemSleepDisabled)
    from terminal_stats import TerminalLog
    from advice_worker import AdviceWorker

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
    advisor = AdviceWorker()
    advice_target = [None]
    background = BackgroundActivity(NSProcessInfo.processInfo(),
        NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityIdleSystemSleepDisabled,
        getattr(WebKit, "WKInactiveSchedulingPolicyNone", None), log.write)
    recovery = AutoplayRecovery(log.write, lambda enabled:
        background.update(view, recovery.session, True) if enabled else background.release())

    class Delegate(NSObject):
        def userContentController_didReceiveScriptMessage_(self, controller, message):
            origin = message.frameInfo().securityOrigin()
            if not message.frameInfo().isMainFrame() or str(origin.protocol()) != "https" or str(origin.host()) != "game.maj-soul.com":
                return
            try:
                event = json.loads(str(message.body()))
                if event['kind'] == 'automation_intent' and message.webView() == view:
                    recovery.on_intent(event)
                log.accept(event)
                if event['kind'] == 'turn':
                    advice_target[0] = message.webView()
                    advisor.submit(f"{event['session']}:{event['serial']}", event['state'])
                elif event['kind'] in ('status', 'error'):
                    advisor.invalidate()
                update = overlay_update(event)
                if update:
                    message.webView().evaluateJavaScript_completionHandler_(update, None)
            except Exception as error:
                print(f"[记录失败] {error}", file=sys.stderr, flush=True)

        def webView_didFailProvisionalNavigation_withError_(self, view, navigation, error):
            if view == window.contentView():
                controlled = recovery.navigation_failed(view, navigation)
                background.navigation_failed(view, navigation, resume_activity=not controlled)
            if error.code() != -999:
                advisor.invalidate()
                log.write(f"[页面加载失败] {error.localizedDescription()}")

        def webView_didFailNavigation_withError_(self, view, navigation, error):
            self.webView_didFailProvisionalNavigation_withError_(view, navigation, error)

        def webView_didStartProvisionalNavigation_(self, view, navigation):
            if view == window.contentView():
                controlled = recovery.navigation_started(navigation)
                background.navigation_started(navigation, preserve_activity=controlled)
                advisor.invalidate()
                advice_target[0] = None

        def webView_didCommitNavigation_(self, view, navigation):
            if view == window.contentView():
                controlled = recovery.page_committed(navigation)
                background.page_committed(navigation, preserve_activity=controlled)

        def webViewWebContentProcessDidTerminate_(self, view):
            advisor.invalidate()
            if view == window.contentView():
                recovery.close()
                background.reset_page()
                advice_target[0] = None
            log.write("[页面进程已退出] 监听中断，请关闭窗口后重新启动程序。")

        def windowWillClose_(self, notification):
            if notification.object() is window:
                recovery.close()
                background.reset_page()
                advisor.close()
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
        (ROOT / "background.js").read_text(encoding="utf-8"), WebKit.WKUserScriptInjectionTimeAtDocumentStart, True))
    controller.addUserScript_(WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        (ROOT / "overlay.js").read_text(encoding="utf-8"), WebKit.WKUserScriptInjectionTimeAtDocumentStart, True))
    controller.addUserScript_(script)
    for name in ('unity_actions.js', 'unity_lobby.js', 'autoplay.js'):
        controller.addUserScript_(WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            (ROOT / name).read_text(encoding='utf-8'), WebKit.WKUserScriptInjectionTimeAtDocumentStart, True))
    window, view = make_window(config, "Maj-Soul++")
    view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_("https://game.maj-soul.com/1/")))
    app.activateIgnoringOtherApps_(True)
    def deliver_advice(timer):
        recovery.tick(view)
        background.pulse(view, time.monotonic(), not bool(window.occlusionState() & AppKit.NSWindowOcclusionStateVisible))
        packet = advisor.take_result()
        if packet and advice_target[0] is not None:
            # WebKit calls stay on the UI thread; slow or superseded work never blocks it.
            advice_target[0].evaluateJavaScript_completionHandler_(overlay_update(packet), None)
            with log.json_path.open('a', encoding='utf-8') as file:
                file.write(json.dumps(packet, ensure_ascii=False) + '\n')
    timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.05, True, deliver_advice)
    signal.signal(signal.SIGINT, lambda signum, frame: app.terminate_(None))
    signal.signal(signal.SIGTERM, lambda signum, frame: app.terminate_(None))
    try:
        app.run()
    finally:
        recovery.close()
        background.reset_page()
        timer.invalidate()
        advisor.close()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("--verify-native", "--verify-overlay", "--verify-advisor"):
        # Exercise the packaged runtime offline, without touching the game profile.
        import runpy
        test_root = ROOT / "source/tests" if getattr(sys, "frozen", False) else ROOT.parent / "tests"
        if sys.argv[1] == '--verify-advisor':
            import unittest
            suite = unittest.defaultTestLoader.discover(str(test_root), pattern='test_advisor*.py')
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            raise SystemExit(0 if result.wasSuccessful() else 1)
        test_name = "test_native.py" if sys.argv[1] == '--verify-native' else "test_overlay.py"
        sys.argv = [str(test_root / test_name)]
        runpy.run_path(str(test_root / test_name), run_name="__main__")
    else:
        main()
