"""Offline native watchdog regressions; no WebKit, account, or network required."""
import json
import unittest

from autoplay_recovery import AutoplayRecovery


class View:
    def __init__(self):
        self.calls = []
        self.reloads = []

    def evaluateJavaScript_completionHandler_(self, script, callback):
        def completed(value, error):
            # The native boundary requests JSON text so PyObjC never has to
            # bridge arbitrary JS objects into NSDictionary subclasses.
            callback(json.dumps(value) if isinstance(value, dict) else value, error)
        self.calls.append((script, completed if callback is not None else None))

    def reload(self):
        navigation = object()
        self.reloads.append(navigation)
        return navigation


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.logs, self.activity = [], []
        self.view = View()
        self.recovery = AutoplayRecovery(self.logs.append, self.activity.append, lambda: self.now)
        self.intent('init', False, 0)
        self.intent('user', True, 1)

    def intent(self, source, enabled, revision, session='page'):
        self.recovery.on_intent({'source': source, 'session': session, 'revision': revision,
            'enabled': enabled, 'playerCount': 3, 'roundCount': 2})

    def snapshot(self, **extra):
        return dict(session='page', revision=1, enabled=True, playerCount=3, roundCount=2,
                    stalled=True, progress=1, phase='reconnecting', fault=None, **extra)

    def reply(self, value, error=None):
        self.view.calls[-1][1](value, error)

    def poll(self, at, value=None):
        self.now = at
        self.recovery.tick(self.view)
        self.reply(self.snapshot() if value is None else value)

    def prepare(self):
        self.poll(0)
        self.poll(45)
        self.assertIn('.prepare(', self.view.calls[-1][0])
        nonce = self.recovery.ticket['nonce']
        packet = self.snapshot()
        packet.update(nonce=nonce, checkpoint={'playerCount': 3, 'roundCount': 2, 'guards': ['opaque']})
        self.reply(packet)
        self.assertEqual(len(self.view.reloads), 1)
        return self.view.reloads[-1]

    def restore(self, navigation, session='replacement'):
        self.recovery.navigation_started(navigation)
        self.recovery.page_committed(navigation)
        self.intent('init', False, 0, session)
        self.now += 1
        self.recovery.tick(self.view)
        fresh = dict(self.snapshot(), session=session, revision=0, enabled=False)
        self.reply(fresh)
        self.assertIn('.restore(', self.view.calls[-1][0])
        restored = dict(fresh, revision=1, enabled=True, restored=True)
        self.intent('restore', True, 1, session)
        self.reply(restored)
        return restored

    def test_heartbeats_and_repeated_waiting_do_not_postpone_bounded_reload(self):
        self.poll(0)
        for at in (10, 20, 30, 44):
            self.poll(at, dict(self.snapshot(), heartbeat=at, serial=at * 10))
            self.assertEqual(self.view.reloads, [])
        self.poll(45, dict(self.snapshot(), heartbeat=45, serial=450))
        self.assertIn('.prepare(', self.view.calls[-1][0])
        self.assertEqual(self.view.reloads, [], 'freeze/guard acknowledgement precedes reload')

    def test_normal_reconnect_and_idle_opponents_never_reload(self):
        self.poll(0)
        self.poll(30, dict(self.snapshot(), stalled=False, phase='playing', progress=2))
        self.poll(400, dict(self.snapshot(), stalled=False, phase='playing', progress=2))
        self.assertEqual(self.view.reloads, [])
        self.assertNotIn('.prepare(', self.view.calls[-1][0])

    def test_real_progress_extends_grace_but_repeated_progress_does_not(self):
        self.poll(0)
        progressed = dict(self.snapshot(), progress=2)
        self.poll(40, progressed)
        self.poll(70, progressed)
        self.assertNotIn('.prepare(', self.view.calls[-1][0])
        self.poll(85, progressed)
        self.assertIn('.prepare(', self.view.calls[-1][0])

    def test_repeated_auth_progress_cannot_leave_an_untrusted_recovery_waiting_forever(self):
        self.poll(0)
        for progress, at in enumerate((40, 80, 120, 160, 179), 2):
            self.poll(at, dict(self.snapshot(), progress=progress))
            self.assertNotIn('.prepare(', self.view.calls[-1][0])
            self.assertEqual(self.view.reloads, [])
        self.poll(180, dict(self.snapshot(), progress=7))
        self.assertIn('.prepare(', self.view.calls[-1][0],
                      'authentication churn without a trusted board needs a bounded fallback')
        self.assertEqual(self.view.reloads, [], 'a bounded wait still requires freeze acknowledgement')

    def test_only_controlled_navigation_consumes_one_shot_resume(self):
        navigation = self.prepare()
        restored = self.restore(navigation)
        self.assertTrue(self.recovery.enabled)
        self.assertEqual(self.recovery.attempts, 1)
        self.assertIsNone(self.recovery.ticket)
        self.assertIn('"roundCount": 2', next(s for s, _ in self.view.calls if '.restore(' in s))
        self.recovery.navigation_started(object())
        self.intent('init', False, 0, 'manual-refresh')
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.ticket)

    def test_user_off_during_prepare_invalidates_late_callback(self):
        self.poll(0)
        self.poll(45)
        callback = self.view.calls[-1][1]
        nonce = self.recovery.ticket['nonce']
        self.intent('user', False, 2)
        callback(dict(self.snapshot(), nonce=nonce, checkpoint={}), None)
        self.assertEqual(self.view.reloads, [])
        self.assertFalse(self.recovery.enabled)
        self.assertFalse(self.activity[-1])

    def test_old_page_off_after_reload_revokes_pending_restore(self):
        navigation = self.prepare()
        self.recovery.navigation_started(navigation)
        self.intent('user', False, 2)
        self.recovery.page_committed(navigation)
        self.intent('init', False, 0, 'replacement')
        self.now = 50
        self.recovery.tick(self.view)
        self.assertFalse(self.recovery.enabled)
        self.assertFalse(any('.restore(' in script for script, _ in self.view.calls))

    def test_manual_input_in_new_page_wins_before_and_during_restore(self):
        navigation = self.prepare()
        self.recovery.navigation_started(navigation)
        self.recovery.page_committed(navigation)
        self.intent('init', False, 0, 'replacement')
        self.now += 1
        self.recovery.tick(self.view)
        self.reply(dict(self.snapshot(), session='replacement', revision=0, enabled=False))
        callback = self.view.calls[-1][1]
        self.intent('user', False, 1, 'replacement')
        callback(dict(self.snapshot(), session='replacement', restored=True), None)
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.ticket)
        self.assertFalse(self.activity[-1])

    def test_stale_poll_cannot_start_recovery_after_mode_or_off_change(self):
        self.recovery.tick(self.view)
        callback = self.view.calls[-1][1]
        self.intent('user', False, 2)
        self.intent('user', True, 3)
        callback(self.snapshot(), None)
        self.assertEqual(self.view.reloads, [])
        self.assertIsNone(self.recovery.stalled_since)

    def test_server_error_is_not_overwritten_or_reloaded(self):
        self.poll(0)
        self.poll(45, dict(self.snapshot(), enabled=False, revision=2, fault='服务器拒绝操作（1204）'))
        self.assertFalse(self.recovery.enabled)
        self.assertEqual(self.view.reloads, [])
        self.assertFalse(any('.fail(' in script for script, _ in self.view.calls))

    def test_unresponsive_page_times_out_without_reusing_old_checkpoint(self):
        self.recovery.tick(self.view)
        callback = self.view.calls[-1][1]
        self.now = 11
        self.recovery.tick(self.view)
        callback(self.snapshot(), None)
        self.assertFalse(self.recovery.enabled)
        self.assertEqual(self.view.reloads, [])
        self.assertTrue(any('页面未回应' in line for line in self.logs))

    def test_backoff_three_attempt_limit_survives_healthy_intervals(self):
        nav = self.prepare()
        state = self.restore(nav)
        for attempt, delay in ((2, 90), (3, 180)):
            self.now += 1
            self.recovery.tick(self.view)
            self.reply(dict(state, stalled=False, progress=10))
            start = self.now + 1
            self.poll(start, dict(state, stalled=True, progress=10))
            self.poll(start + delay - 1, dict(state, stalled=True, progress=10))
            self.assertEqual(len(self.view.reloads), attempt - 1)
            self.poll(start + delay, dict(state, stalled=True, progress=10))
            nonce = self.recovery.ticket['nonce']
            self.reply(dict(state, nonce=nonce, checkpoint={'playerCount': 3, 'roundCount': 2}))
            nav = self.view.reloads[-1]
            state = self.restore(nav, 'replacement-' + str(attempt))
        self.poll(self.now + 1, state)
        self.poll(self.now + 181, state)
        self.assertEqual(len(self.view.reloads), 3)
        self.assertFalse(self.recovery.enabled)
        self.assertTrue(any('3 次' in line for line in self.logs))

    def test_failed_navigation_and_content_termination_release_activity(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.recovery.navigation_failed(self.view, nav)
        self.assertFalse(self.recovery.enabled)
        self.assertFalse(self.activity[-1])
        self.intent('user', True, 3)
        self.recovery.close()
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.ticket)
        self.assertFalse(self.activity[-1])

    def test_cancelled_ordinary_navigation_resumes_watchdog_only_from_fresh_same_page_intent(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.setUp()
                self.recovery.attempts = 2
                navigation = object()
                self.assertFalse(self.recovery.navigation_started(navigation))
                self.assertFalse(self.recovery.enabled)
                self.assertTrue(self.recovery.navigation_failed(self.view, navigation))
                self.reply(dict(self.snapshot(), enabled=enabled))
                self.assertEqual(self.recovery.enabled, enabled)
                self.assertEqual(self.recovery.attempts, 2)
                self.assertEqual(self.activity[-1], enabled)

    def test_cancelled_navigation_query_cannot_override_later_user_off(self):
        navigation = object()
        self.recovery.navigation_started(navigation)
        self.recovery.navigation_failed(self.view, navigation)
        callback = self.view.calls[-1][1]
        self.intent('user', False, 2)
        callback(self.snapshot(), None)
        self.assertFalse(self.recovery.enabled)
        self.assertFalse(self.activity[-1])

    def test_replaced_ordinary_navigation_retains_original_watchdog_intent(self):
        self.recovery.attempts = 2
        first, second = object(), object()
        self.recovery.navigation_started(first)
        self.recovery.navigation_started(second)
        self.assertFalse(self.recovery.navigation_failed(self.view, first))
        self.assertEqual(self.view.calls, [], 'the superseded navigation must not query the current page')
        self.assertTrue(self.recovery.navigation_failed(self.view, second))
        self.reply(self.snapshot())
        self.assertTrue(self.recovery.enabled)
        self.assertTrue(self.activity[-1])
        self.assertEqual(self.recovery.attempts, 2)

    def test_new_navigation_during_resume_query_uses_only_the_newest_page_query(self):
        self.recovery.attempts = 2
        first, second = object(), object()
        self.recovery.navigation_started(first)
        self.assertTrue(self.recovery.navigation_failed(self.view, first))
        old_callback = self.view.calls[-1][1]
        self.recovery.navigation_started(second)
        self.assertTrue(self.recovery.navigation_failed(self.view, second))
        current_request = self.recovery.pending
        old_callback(self.snapshot(), None)
        self.assertIs(self.recovery.pending, current_request)
        self.assertFalse(self.recovery.enabled)
        self.reply(self.snapshot())
        self.assertTrue(self.recovery.enabled)
        self.assertTrue(self.activity[-1])
        self.assertEqual(self.recovery.attempts, 2)

    def test_mode_change_during_suspended_navigation_does_not_replenish_attempts(self):
        self.recovery.attempts = 2
        self.recovery.navigation_started(object())
        self.intent('user', True, 2)
        self.assertTrue(self.recovery.enabled)
        self.assertEqual(self.recovery.attempts, 2, 'temporary native suspension is not a user off/on cycle')
        self.intent('user', False, 3)
        self.intent('user', True, 4)
        self.assertEqual(self.recovery.attempts, 0, 'a real explicit off/on cycle starts a new budget')

    def test_old_page_mode_change_after_new_init_revokes_old_preferences(self):
        navigation = self.prepare()
        self.recovery.navigation_started(navigation)
        self.recovery.page_committed(navigation)
        self.intent('init', False, 0, 'replacement')
        self.intent('user', True, 2, 'page')
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.ticket)

    def test_unrelated_commit_and_stale_page_intent_cannot_enable(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.recovery.page_committed(object())
        self.assertFalse(self.recovery.enabled)
        self.intent('init', False, 0, 'new')
        self.intent('user', True, 50, 'page')
        self.assertFalse(self.recovery.enabled)

    def test_document_init_before_commit_preserves_controlled_restore(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.intent('init', False, 0, 'replacement')
        self.assertTrue(self.recovery.enabled)
        calls = len(self.view.calls)
        self.now += 1
        self.recovery.tick(self.view)
        self.assertEqual(len(self.view.calls), calls, 'do not restore an uncommitted document')
        self.recovery.page_committed(nav)
        self.recovery.tick(self.view)
        fresh = dict(self.snapshot(), session='replacement', revision=0, enabled=False)
        self.reply(fresh)
        self.intent('restore', True, 1, 'replacement')
        self.reply(dict(fresh, revision=1, enabled=True, restored=True))
        self.assertTrue(self.recovery.enabled)
        self.assertIsNone(self.recovery.ticket)

    def test_fresh_snapshot_before_delayed_init_message_preserves_that_document(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.recovery.page_committed(nav)
        self.now += 1
        self.recovery.tick(self.view)
        fresh = dict(self.snapshot(), session='replacement', revision=0, enabled=False)
        self.reply(fresh)
        self.assertTrue(self.recovery.enabled, 'bridge init and evaluation completion may arrive separately')
        self.intent('init', False, 0, 'replacement')
        self.assertIn('.restore(', self.view.calls[-1][0])
        self.intent('restore', True, 1, 'replacement')
        self.reply(dict(fresh, revision=1, enabled=True, restored=True))
        self.assertTrue(self.recovery.enabled)

    def test_restore_result_can_precede_its_intent_message(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.recovery.page_committed(nav)
        self.intent('init', False, 0, 'replacement')
        self.now += 1
        self.recovery.tick(self.view)
        fresh = dict(self.snapshot(), session='replacement', revision=0, enabled=False)
        self.reply(fresh)
        self.reply(dict(fresh, revision=1, enabled=True, restored=True))
        self.intent('restore', True, 1, 'replacement')
        self.assertTrue(self.recovery.enabled)
        self.assertEqual(self.recovery.revision, 1)
        self.assertIsNone(self.recovery.ticket)
        self.assertFalse(any('.fail(' in script for script, _ in self.view.calls))

    def test_mode_revision_does_not_replenish_reload_budget(self):
        self.restore(self.prepare())
        self.intent('user', True, 2, 'replacement')
        self.assertTrue(self.recovery.enabled)
        self.assertEqual(self.recovery.attempts, 1)
        state = dict(self.snapshot(), session='replacement', revision=2, playerCount=4, roundCount=1)
        start = self.now + 1
        self.poll(start, state)
        self.poll(start + 45, state)
        self.assertNotIn('.prepare(', self.view.calls[-1][0])
        self.poll(start + 90, state)
        self.assertIn('.prepare(', self.view.calls[-1][0])

    def test_retired_page_off_after_new_init_still_revokes_reload(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.intent('init', False, 0, 'replacement')
        self.intent('pause', False, 2, 'page')
        self.recovery.page_committed(nav)
        self.now += 1
        self.recovery.tick(self.view)
        self.assertFalse(self.recovery.enabled)
        self.assertFalse(any('.restore(' in script for script, _ in self.view.calls))

    def test_document_without_recovery_bridge_expires_its_load_ticket(self):
        nav = self.prepare()
        self.recovery.navigation_started(nav)
        self.recovery.page_committed(nav)
        self.now += 1
        self.recovery.tick(self.view)
        self.reply(None)
        self.assertTrue(self.recovery.enabled)
        self.now = 105
        self.recovery.tick(self.view)
        self.assertFalse(self.recovery.enabled)
        self.assertFalse(self.activity[-1])
        self.assertTrue(any('超过 60 秒' in line for line in self.logs))

    def test_javascript_query_failure_cancels_without_reload(self):
        self.recovery.tick(self.view)
        self.reply(None, RuntimeError('document unavailable'))
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.pending)
        self.assertEqual(self.view.reloads, [])
        self.assertTrue(any('页面恢复检查失败' in line for line in self.logs))

    def test_reload_api_failure_consumes_no_resumable_credential(self):
        self.poll(0)
        self.poll(45)
        nonce = self.recovery.ticket['nonce']
        self.view.reload = lambda: None
        self.reply(dict(self.snapshot(), nonce=nonce, checkpoint={}))
        self.assertFalse(self.recovery.enabled)
        self.assertIsNone(self.recovery.ticket)
        self.assertFalse(self.activity[-1])
        self.assertTrue(any('无法启动恢复页面' in line for line in self.logs))


if __name__ == '__main__':
    unittest.main()
