"""Python output regression checks, using a recorded real turn snapshot."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from threading import Event, current_thread
import unittest
from unittest.mock import Mock

from advice_worker import AdviceWorker
import monitor
from terminal_stats import TerminalLog, format_turn
from monitor import BackgroundActivity, accept_event, deliver_advice, overlay_update

ROOT = Path(__file__).resolve().parent


class NativeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.advisor, self.log, self.process, self.view = Mock(), Mock(), Mock(), Mock()
        self.preferences = self.view.configuration().preferences()
        self.preferences.inactiveSchedulingPolicy.return_value = 1
        self.preferences.setInactiveSchedulingPolicy_.side_effect = lambda policy: self.calls.append(('policy', policy))
        self.process.endActivity_.side_effect = lambda token: self.calls.append(('release', token))
        self.background = BackgroundActivity(self.process, 123, 2, self.log.write)
        self.addCleanup(self.background.release)
        self.target = [None]
        self.advisor.submit.side_effect = lambda key, state: self.calls.append(('submit', key, state, self.target[0]))
        self.advisor.invalidate.side_effect = lambda *args: self.calls.append(('invalidate', *args))
        self.log.accept.side_effect = lambda event: self.calls.append(('log', event['kind']))
        # Execute the production handler and recovery callback without starting AppKit,
        # opening the user's profile, or substituting their dispatch implementation.
        source = Path(monitor.__file__)
        main = next(node for node in ast.parse(source.read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        recovery = next(node for node in main.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == 'recovery' for target in node.targets))
        delegate = next(node for node in main.body if isinstance(node, ast.ClassDef) and node.name == 'Delegate')
        handler = next(node for node in delegate.body if isinstance(node, ast.FunctionDef)
                       and node.name == 'userContentController_didReceiveScriptMessage_')
        namespace = {**vars(monitor), 'advisor': self.advisor, 'log': self.log, 'view': self.view,
                     'background': self.background, 'advice_target': self.target}
        exec(compile(ast.Module(body=[recovery, handler], type_ignores=[]), str(source), 'exec'), namespace)
        self.recovery, self.handler = namespace['recovery'], namespace[handler.name]

    def send(self, event, view=None):
        message = Mock()
        message.frameInfo().isMainFrame.return_value = True
        message.frameInfo().securityOrigin().protocol.return_value = 'https'
        message.frameInfo().securityOrigin().host.return_value = 'game.maj-soul.com'
        message.webView.return_value = self.view if view is None else view
        message.body.return_value = json.dumps(event)
        self.handler(None, None, message)

    def test_synchronous_off_releases_recovery_activity_before_logging_and_telemetry_cannot_reopen(self):
        intent = {'kind': 'automation_intent', 'session': 'page', 'revision': 0, 'source': 'init', 'enabled': False}
        self.send(intent)
        self.send({**intent, 'revision': 1, 'source': 'user', 'enabled': True})
        token = self.background.token
        self.assertIsNotNone(token)
        self.assertTrue(self.recovery.enabled)
        self.preferences.setInactiveSchedulingPolicy_.assert_called_with(2)
        self.recovery.pending = object()
        self.calls.clear()
        self.send({**intent, 'revision': 2, 'source': 'user'})
        self.assertEqual(self.calls, [('policy', 1), ('release', token), ('log', 'automation_intent')])
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.pending)
        self.assertIsNone(self.background.token)
        self.calls.clear()
        self.send({'kind': 'automation', 'session': 'page', 'enabled': True})
        self.send({'kind': 'advisor_delivery', 'adviceKey': 'page:1', 'current': False})
        self.assertEqual(self.calls, [('log', 'automation'), ('log', 'advisor_delivery')])
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.background.token)
        self.process.beginActivityWithOptions_reason_.assert_called_once()
        self.process.endActivity_.assert_called_once_with(token)

    def test_handler_sets_delivery_target_and_submits_or_cancels_before_logging(self):
        turn = json.loads((ROOT / 'fixtures/turn.json').read_text())
        self.send(turn)
        self.assertEqual(self.calls, [('submit', f"{turn['session']}:{turn['serial']}", turn['state'], self.view),
                                     ('log', 'turn')])
        self.view.evaluateJavaScript_completionHandler_.assert_called_once()
        for kind in ('advice_invalidated', 'status', 'error'):
            self.calls.clear()
            self.send({'kind': kind, 'adviceKey': 'page:1', 'phase': 'disconnected'})
            expected = ('invalidate', 'page:1') if kind == 'advice_invalidated' else ('invalidate',)
            self.assertEqual(self.calls, [expected, ('log', kind)])

    def test_other_webview_intent_cannot_activate_main_window_recovery(self):
        intent = {'kind': 'automation_intent', 'session': 'page', 'revision': 0, 'source': 'init', 'enabled': False}
        self.send(intent)
        self.send({**intent, 'revision': 1, 'source': 'user', 'enabled': True}, view=Mock())
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.background.token)
        self.process.beginActivityWithOptions_reason_.assert_not_called()


class OutputTests(unittest.TestCase):
    def test_advice_is_delivered_to_automation_with_its_original_key(self):
        advice = {'status': 'win', 'action': 'ron', 'message': '当前可荣和'}
        script = overlay_update({'kind': 'advice', 'adviceKey': 'session:42', 'advice': advice})
        self.assertIn('window.__mjStatsOverlay?.update(', script)
        self.assertIn('window.__mjAutoplay?.onAdvice(', script)
        payload = json.loads(script.split('window.__mjAutoplay?.onAdvice(', 1)[1].split(');', 1)[0])
        self.assertEqual(payload['adviceKey'], 'session:42')
        self.assertEqual(payload['advice'], advice)
        self.assertIn('window.__mjMonitor?.onAdvice?.(', script)
        receipt = json.loads(script.split('window.__mjMonitor?.onAdvice?.(', 1)[1][:-2])
        self.assertEqual(receipt, {'adviceKey': 'session:42'})
        self.assertNotIn('__mjAutoplay', overlay_update({'kind': 'status', 'phase': 'waiting'}))

    def test_advisor_is_submitted_or_invalidated_before_event_log_writes(self):
        calls = []
        advisor = Mock()
        advisor.submit.side_effect = lambda key, state: calls.append(('submit', key, state))
        advisor.invalidate.side_effect = lambda *args: calls.append(('invalidate', *args))
        log = Mock()
        log.accept.side_effect = lambda event: calls.append(('log', event['kind']))
        accept_event(advisor, log, {'kind': 'turn', 'session': 's', 'serial': 2, 'state': {'canAct': True}})
        self.assertEqual(calls, [('submit', 's:2', {'canAct': True}), ('log', 'turn')])
        for kind in ('status', 'error', 'advice_invalidated'):
            calls.clear()
            event = {'kind': kind, 'adviceKey': 's:2'}
            accept_event(advisor, log, event)
            invalidate = ('invalidate', 's:2') if kind == 'advice_invalidated' else ('invalidate',)
            self.assertEqual(calls, [invalidate, ('log', kind)])
            if kind == 'advice_invalidated':
                self.assertIsNone(overlay_update(event))
        calls.clear()
        accept_event(advisor, log, {'kind': 'advisor_delivery'})
        self.assertEqual(calls, [('log', 'advisor_delivery')])

    def test_ui_timer_drains_cancellation_diagnostics_without_delivering_stale_advice(self):
        started, release = Event(), Event()
        calculation_threads = []

        def calculate(state):
            calculation_threads.append(current_thread())
            started.set()
            self.assertTrue(release.wait(3))
            return {'status': 'ready'}

        worker = AdviceWorker(calculate)
        try:
            with tempfile.TemporaryDirectory() as folder:
                log = TerminalLog(folder)
                worker.submit('old', {})
                self.assertTrue(started.wait(3))
                accept_event(worker, log, {'kind': 'advice_invalidated', 'session': 's', 'serial': 1,
                                           'adviceKey': 'old'})
                release.set()
                with worker.condition:
                    self.assertTrue(worker.condition.wait_for(lambda: worker.active is None, 3))
                view = Mock()
                deliver_advice(worker, view, log)
                view.evaluateJavaScript_completionHandler_.assert_not_called()
                records = list(map(json.loads, log.json_path.read_text().splitlines()))
                self.assertEqual([r['kind'] for r in records], ['advice_invalidated', 'advisor_timing'])
                self.assertEqual(records[1]['outcome'], 'invalidated')
                self.assertNotEqual(calculation_threads, [current_thread()])
                self.assertEqual(worker.take_diagnostics(), [])
        finally:
            worker.close()
            release.set()
            worker.thread.join(3)

    def test_ui_timer_delivers_the_original_advice_and_logs_packet_timing(self):
        advice = {'status': 'ready', 'elapsedMs': 12.3, 'candidates': [{'score': 9.8}]}
        worker = AdviceWorker(lambda state: advice)
        try:
            with tempfile.TemporaryDirectory() as folder:
                log = TerminalLog(folder)
                worker.submit('s:8', {})
                with worker.condition:
                    self.assertTrue(worker.condition.wait_for(lambda: worker.completed is not None, 3))
                view = Mock()
                deliver_advice(worker, view, log)
                records = list(map(json.loads, log.json_path.read_text().splitlines()))
                self.assertEqual([r['kind'] for r in records], ['advice', 'advisor_timing'])
                self.assertEqual(records[0]['advice'], advice)
                self.assertEqual(records[0]['diagnostics'], {k: v for k, v in records[1].items() if k != 'kind'})
                script = view.evaluateJavaScript_completionHandler_.call_args.args[0]
                payload = json.loads(script.split('window.__mjAutoplay?.onAdvice(', 1)[1].split(');', 1)[0])
                self.assertEqual(payload, records[0])
        finally:
            worker.close()
            worker.thread.join(3)

    def setUp(self):
        self.event = json.loads((ROOT / "fixtures/turn.json").read_text(encoding="utf-8"))

    def test_duplicate_snapshot_is_saved_once_without_console_output(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
            log = TerminalLog(folder)
            log.accept(self.event)
            log.accept(self.event)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(log.text_path.read_text().count("次更新"), 1)
            self.assertEqual(len(log.json_path.read_text().splitlines()), 1)

    def test_title_identifies_initial_deal_and_other_players(self):
        self.event['trigger'] = 'ActionNewRound'
        self.assertIn('开局发牌', format_turn(self.event))
        self.event.update(trigger='ActionDiscardTile', actorSeat=2)
        text = format_turn(self.event)
        self.assertIn('座位2 出牌', text)
        self.assertNotIn('轮到你出牌', text)

    def test_heartbeat_is_silent(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
            log = TerminalLog(folder)
            log.accept({"session": "test", "serial": 1, "kind": "heartbeat"})
            self.assertEqual(out.getvalue(), "")
            self.assertFalse(log.json_path.exists())

    def test_automation_reason_is_logged_without_invalidating_the_advisor(self):
        event = {'session':'test', 'serial':1, 'kind':'automation',
                 'phase':'paused', 'enabled':False, 'message':'等待服务器确认超时'}
        with tempfile.TemporaryDirectory() as folder:
            log = TerminalLog(folder)
            log.accept(event)
            self.assertIn('[自动打牌] 等待服务器确认超时', log.text_path.read_text())
            self.assertIsNone(overlay_update(event))

    def test_riichi_marker_follows_other_players_names(self):
        for players in (3, 4):
            with self.subTest(players=players):
                self.event['state'].update(playerCount=players, selfSeat=0,
                                           riichi=[True, True, False, True])
                text = format_turn(self.event)
                self.assertIn('座位0 弃牌', text)
                self.assertIn('座位1（已立直） 弃牌', text)
                self.assertIn('座位2 弃牌', text)
                self.assertNotIn('座位0（已立直）', text)
                self.assertNotIn('座位2（已立直）', text)
                self.assertEqual(text.count('（已立直）'), players - 2)

    def test_unconfirmed_riichi_discard_does_not_mark_player(self):
        self.event['state']['riichi'] = [False] * 4
        self.event['state']['rivers'][1] = [{'tile': '1p', 'riichi': True}]
        text = format_turn(self.event)
        self.assertIn('1筒[立直]', text)
        self.assertNotIn('（已立直）', text)

    def test_incomplete_hand_does_not_count_stale_tiles(self):
        event = deepcopy(self.event)
        event["state"]["handComplete"] = False
        text = format_turn(event)
        event["state"]["hand"] += ["1m"] * 50
        self.assertEqual(text, format_turn(event))
        self.assertIn("本人完整手牌：尚未取得", text)
        self.assertIn("仅已观察部分", text)


if __name__ == "__main__":
    unittest.main()
