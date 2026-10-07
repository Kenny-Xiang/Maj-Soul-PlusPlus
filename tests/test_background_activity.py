"""Native automation activity is bounded to the current page and user intent."""
import sys
import unittest

from monitor import BackgroundActivity


class Process:
    def __init__(self):
        self.started = []
        self.ended = []

    def beginActivityWithOptions_reason_(self, options, reason):
        token = object()
        self.started.append((token, options, reason))
        return token

    def endActivity_(self, token):
        self.ended.append(token)


class Preferences:
    def __init__(self, policy=1):
        self.policy = policy
        self.writes = []
        self.fail = False

    def inactiveSchedulingPolicy(self):
        return self.policy

    def setInactiveSchedulingPolicy_(self, policy):
        self.writes.append(policy)
        if self.fail:
            raise RuntimeError('policy failed')
        self.policy = policy


class View:
    def __init__(self, preferences=None):
        self.prefs = preferences if preferences is not None else Preferences()
        self.scripts = []

    def configuration(self):
        return self

    def preferences(self):
        return self.prefs

    def evaluateJavaScript_completionHandler_(self, source, completed):
        self.scripts.append((source, completed))


class BackgroundActivityTests(unittest.TestCase):
    def setUp(self):
        self.process, self.view, self.logs = Process(), View(), []
        self.activity = BackgroundActivity(self.process, 123, 2, self.logs.append)
        self.addCleanup(self.activity.release)

    def test_only_enabled_boolean_holds_one_activity_and_restores_original_policy(self):
        for enabled in (False, None, 'true', 1):
            self.activity.update(self.view, 'page', enabled)
        self.assertEqual(self.process.started, [])
        self.activity.update(self.view, 'page', True)
        self.activity.update(self.view, 'page', True)
        self.assertEqual(len(self.process.started), 1)
        self.assertEqual(self.process.started[0][1], 123)
        self.assertEqual(self.view.prefs.policy, 2)
        self.activity.update(self.view, 'page', False)
        self.assertEqual(self.view.prefs.policy, 1)
        self.assertEqual(self.process.ended, [self.process.started[0][0]])
        self.activity.release()
        self.assertEqual(len(self.process.ended), 1)

    def test_navigation_or_termination_releases_and_rejects_retired_page_messages(self):
        self.activity.update(self.view, 'old', True)
        self.activity.reset_page()
        self.assertEqual(len(self.process.ended), 1)
        self.activity.update(self.view, 'old', True)
        self.activity.update(self.view, 'new', True)
        self.assertEqual(len(self.process.started), 1)
        self.activity.page_committed()
        self.activity.update(self.view, 'new', False)
        self.activity.update(self.view, 'old', True)
        self.assertEqual(len(self.process.started), 1)
        self.activity.update(self.view, 'new', True)
        self.assertEqual(len(self.process.started), 2)
        self.activity.update(self.view, 'old', False)
        self.assertIsNotNone(self.activity.token)

    def test_new_document_idle_releases_even_without_a_navigation_callback(self):
        self.activity.update(self.view, 'old', True)
        self.activity.update(self.view, 'new', False)
        self.assertEqual(len(self.process.ended), 1)
        self.assertIsNone(self.activity.token)
        self.activity.update(self.view, 'old', True)
        self.assertEqual(len(self.process.started), 1)

    def test_failed_provisional_navigation_restores_only_the_existing_pages_actual_intent(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                process, view = Process(), View()
                activity = BackgroundActivity(process, 123, 2, self.logs.append)
                self.addCleanup(activity.release)
                activity.update(view, 'page', True)
                navigation = object()
                activity.navigation_started(navigation)
                self.assertIsNone(activity.token)
                self.assertNotIn('page', activity.retired_sessions)
                activity.navigation_failed(view, navigation)
                self.assertIsNone(activity.token, 'cached intent alone cannot reacquire activity')
                self.assertIn("location.protocol === 'https:'", view.scripts[-1][0])
                self.assertIn('getStatus().enabled === true', view.scripts[-1][0])
                view.scripts[-1][1](enabled, None)
                self.assertEqual(activity.token is not None, enabled)
                self.assertEqual(len(process.started), 2 if enabled else 1)

    def test_old_navigation_failure_and_old_resume_query_cannot_interfere_with_a_new_page(self):
        self.activity.update(self.view, 'old', True)
        first, second, third = object(), object(), object()
        self.activity.navigation_started(first)
        self.activity.navigation_started(second)
        self.activity.navigation_failed(self.view, first)
        self.assertEqual(self.view.scripts, [])
        self.assertFalse(self.activity.accepting)
        self.activity.navigation_failed(self.view, second)
        resume = self.view.scripts[-1][1]
        self.activity.navigation_started(third)
        self.activity.page_committed(third)
        self.activity.update(self.view, 'new', False)
        resume(True, None)
        self.activity.update(self.view, 'old', True)
        self.assertIsNone(self.activity.token)
        self.assertEqual(len(self.process.started), 1)

    def test_fresh_disable_supersedes_the_navigation_failure_query(self):
        self.activity.update(self.view, 'page', True)
        navigation = object()
        self.activity.navigation_started(navigation)
        self.activity.navigation_failed(self.view, navigation)
        resume = self.view.scripts[-1][1]
        self.activity.update(self.view, 'page', False)
        resume(True, None)
        self.assertIsNone(self.activity.token)
        self.assertEqual(len(self.process.started), 1)

    def test_failed_navigation_status_query_does_not_blindly_restore_activity(self):
        self.activity.update(self.view, 'page', True)
        navigation = object()
        self.activity.navigation_started(navigation)
        self.activity.navigation_failed(self.view, navigation)
        self.view.scripts[-1][1](None, RuntimeError('old document unavailable'))
        self.assertIsNone(self.activity.token)
        self.assertTrue(any('无法确认自动状态' in entry for entry in self.logs))
        self.activity.update(self.view, 'page', True)
        self.assertIsNotNone(self.activity.token, 'a later valid current-page event can restore activity')

    def test_missing_public_webkit_policy_keeps_native_activity_balanced(self):
        self.view.prefs = object()
        self.activity.update(self.view, 'page', True)
        self.assertEqual(len(self.process.started), 1)
        self.assertTrue(any('不可用' in entry for entry in self.logs))
        self.activity.release()
        self.assertEqual(len(self.process.ended), 1)

    def test_policy_failures_still_release_the_native_token(self):
        self.view.prefs.fail = True
        self.activity.update(self.view, 'page', True)
        self.activity.release()
        self.assertEqual(len(self.process.started), 1)
        self.assertEqual(self.process.ended, [self.process.started[0][0]])
        self.assertEqual(self.view.prefs.writes, [2, 1])

    def test_pulse_requires_enabled_occluded_view_and_is_rate_and_inflight_limited(self):
        self.activity.pulse(self.view, 0, True)
        self.activity.update(self.view, 'page', True)
        self.activity.pulse(self.view, 0, False)
        self.assertEqual(self.view.scripts, [])
        self.activity.pulse(self.view, 0, True)
        self.assertEqual(len(self.view.scripts), 1)
        self.assertEqual(self.view.scripts[0][0], 'window.__mjBackground?.pulse();')
        self.activity.pulse(self.view, 10, True)
        self.assertEqual(len(self.view.scripts), 1)
        self.view.scripts[0][1](None, None)
        self.activity.pulse(self.view, .249, True)
        self.assertEqual(len(self.view.scripts), 1)
        self.activity.pulse(self.view, .25, True)
        self.assertEqual(len(self.view.scripts), 2)
        self.activity.release()
        self.activity.pulse(self.view, 20, True)
        self.assertEqual(len(self.view.scripts), 2)

    def test_old_pulse_completion_cannot_clear_a_new_pages_inflight_request(self):
        self.activity.update(self.view, 'old', True)
        self.activity.pulse(self.view, 0, True)
        old_callback = self.view.scripts[0][1]
        self.activity.reset_page()
        self.activity.page_committed()
        self.activity.update(self.view, 'new', True)
        self.activity.pulse(self.view, 1, True)
        current_request = self.activity.pulse_request
        old_callback(None, RuntimeError('old page'))
        self.assertIs(self.activity.pulse_request, current_request)
        self.assertFalse(any('old page' in entry for entry in self.logs))
        self.activity.pulse(self.view, 2, True)
        self.assertEqual(len(self.view.scripts), 2)

    def test_controlled_navigation_holds_same_activity_until_restored_user_turns_off(self):
        self.activity.update(self.view, 'old', True)
        token = self.activity.token
        self.activity.pulse(self.view, 0, True)
        old_pulse = self.view.scripts[-1][1]
        navigation = object()
        self.activity.navigation_started(navigation, preserve_activity=True)
        self.assertIs(self.activity.token, token)
        self.activity.pulse(self.view, 1, True)
        self.assertEqual(len(self.view.scripts), 1, 'suspend pulse during navigation')
        self.activity.page_committed(navigation, preserve_activity=True)
        self.activity.update(self.view, 'new', True)
        self.assertIs(self.activity.token, token)
        self.assertEqual(self.process.ended, [])
        self.assertEqual(len(self.process.started), 1)
        self.activity.pulse(self.view, 2, True)
        new_request = self.activity.pulse_request
        old_pulse(None, None)
        self.assertIs(self.activity.pulse_request, new_request)
        self.activity.update(self.view, 'old', False)
        self.assertIs(self.activity.token, token, 'retired page cannot revoke a consumed recovery')
        self.activity.update(self.view, 'new', False)
        self.assertIsNone(self.activity.token)
        self.assertEqual(self.process.ended, [token])
        self.assertEqual(self.view.prefs.policy, 1)

    def test_user_off_during_controlled_load_releases_preserved_activity(self):
        self.activity.update(self.view, 'old', True)
        token = self.activity.token
        navigation = object()
        self.activity.navigation_started(navigation, preserve_activity=True)
        # AutoplayRecovery.close invokes release directly, including while
        # provisional navigation rejects ordinary activity update messages.
        self.activity.release()
        self.activity.page_committed(navigation)
        self.activity.update(self.view, 'new', False)
        self.assertEqual(self.process.ended, [token])
        self.assertEqual(len(self.process.started), 1)
        self.assertIsNone(self.activity.token)

    def test_failed_controlled_reload_cannot_reacquire_from_old_page_status(self):
        self.activity.update(self.view, 'old', True)
        token = self.activity.token
        navigation = object()
        self.activity.navigation_started(navigation, preserve_activity=True)
        # The recovery supervisor revokes intent before dispatching its
        # best-effort page pause. Its failure must not start an enabled query.
        self.activity.release()
        self.activity.navigation_failed(self.view, navigation, resume_activity=False)
        self.assertEqual(self.view.scripts, [])
        self.assertEqual(self.process.ended, [token])
        self.assertIsNone(self.activity.token)

    def test_pulse_failure_is_observable_and_does_not_permanently_block_delivery(self):
        self.activity.update(self.view, 'page', True)
        self.activity.pulse(self.view, 0, True)
        self.view.scripts[0][1](None, RuntimeError('not delivered'))
        self.assertIsNone(self.activity.pulse_request)
        self.activity.pulse(self.view, .25, True)
        self.view.scripts[1][1](None, RuntimeError('not delivered'))
        self.assertEqual(sum('not delivered' in entry for entry in self.logs), 1)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS public API metadata')
    def test_runtime_exposes_public_policy_and_does_not_request_display_sleep_prevention(self):
        import WebKit
        from Foundation import (NSProcessInfo, NSActivityUserInitiated,
                                NSActivityUserInitiatedAllowingIdleSystemSleep,
                                NSActivityIdleSystemSleepDisabled, NSActivityIdleDisplaySleepDisabled)
        options = NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityIdleSystemSleepDisabled
        self.assertEqual(options, NSActivityUserInitiated)
        self.assertEqual(options & NSActivityIdleDisplaySleepDisabled, 0)
        self.assertTrue(hasattr(NSProcessInfo, 'beginActivityWithOptions_reason_'))
        self.assertTrue(hasattr(WebKit.WKPreferences, 'setInactiveSchedulingPolicy_'))
        self.assertEqual(WebKit.WKInactiveSchedulingPolicyNone, 2)


if __name__ == '__main__':
    unittest.main()
