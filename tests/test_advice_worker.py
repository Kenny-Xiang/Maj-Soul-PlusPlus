"""Deterministic concurrency checks: superseded boards must never reach the overlay."""
import json
from pathlib import Path
from threading import Event
import time
import unittest
from unittest.mock import patch

from advice_worker import AdviceWorker
from monitor import overlay_update


def eventually(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.005)
    raise AssertionError('worker did not finish')


class AdviceWorkerTests(unittest.TestCase):
    def test_late_invalidation_for_an_old_key_does_not_cancel_the_current_action(self):
        started, release = Event(), Event()

        def calculate(state):
            started.set()
            self.assertTrue(release.wait(3))
            return {'status': 'ready'}

        worker = AdviceWorker(calculate)
        try:
            worker.submit('current', {'canAct': True})
            self.assertTrue(started.wait(3))
            worker.invalidate('old')
            release.set()
            with worker.condition:
                self.assertTrue(worker.condition.wait_for(lambda: worker.completed is not None, 3))
            worker.invalidate('old')
            result = worker.take_result()
            self.assertEqual(result['adviceKey'], 'current')
            self.assertEqual(result['diagnostics']['outcome'], 'delivered')
        finally:
            worker.close()
            release.set()
            worker.thread.join(3)

    def test_pending_display_updates_are_coalesced_and_action_bypasses_the_delay(self):
        visited = []

        def calculate(state):
            visited.append(state['step'])
            return {'status': 'ready', 'step': state['step']}

        with patch('advice_worker.ANALYSIS_DELAY_SECONDS', 60):
            worker = AdviceWorker(calculate)
            try:
                with worker.condition:
                    worker.submit('display-1', {'phase': 'playing', 'canAct': False, 'step': 1})
                    worker.submit('display-2', {'phase': 'playing', 'canAct': False, 'step': 2})
                    worker.submit('action', {'phase': 'playing', 'canAct': True, 'step': 3})
                result = eventually(worker.take_result)
                self.assertEqual(visited, [3])
                self.assertEqual(result['advice'], {'status': 'ready', 'step': 3})
                records = worker.take_diagnostics()
                self.assertEqual([(r['adviceKey'], r['outcome'], r['stage']) for r in records],
                                 [('display-1', 'superseded', 'queued'),
                                  ('display-2', 'superseded', 'queued'), ('action', 'delivered', 'completed')])
                self.assertIsNone(records[0]['calculateWallMs'])
                self.assertEqual(records[2]['coalesceMs'], 0)
            finally:
                worker.close()
                worker.thread.join(3)

    def test_latest_display_analysis_still_runs_after_quiet_period(self):
        visited = []

        def calculate(state):
            visited.append(state['step'])
            return {'status': 'analysis', 'step': state['step']}

        worker = AdviceWorker(calculate)
        try:
            with worker.condition:
                worker.submit('old', {'phase': 'playing', 'canAct': False, 'step': 1})
                worker.submit('latest', {'phase': 'playing', 'canAct': False, 'step': 2})
            result = eventually(worker.take_result)
            self.assertEqual(visited, [2])
            self.assertEqual(result['advice'], {'status': 'analysis', 'step': 2})
            self.assertEqual(result['diagnostics']['mode'], 'analysis')
            self.assertEqual(result['diagnostics']['coalesceMs'], 100)
            self.assertGreaterEqual(result['diagnostics']['queueMs'], 100)
        finally:
            worker.close()
            worker.thread.join(3)

    def test_action_cancels_running_display_analysis(self):
        started, release = Event(), Event()
        cancellation = []

        def calculate(state, cancelled, *, ranked_limit):
            if not state['canAct']:
                started.set()
                self.assertTrue(release.wait(3))
                cancellation.append(cancelled())
            return {'status': 'ready', 'step': state['step']}

        with patch('advisor.advise', side_effect=calculate):
            worker = AdviceWorker()
            try:
                worker.submit('display', {'phase': 'playing', 'canAct': False, 'step': 1})
                self.assertTrue(started.wait(3))
                worker.submit('action', {'phase': 'playing', 'canAct': True, 'step': 2})
                release.set()
                result = eventually(worker.take_result)
                self.assertEqual(cancellation, [True])
                self.assertEqual(result['adviceKey'], 'action')
                records = worker.take_diagnostics()
                self.assertEqual(records[0]['outcome'], 'superseded')
                self.assertEqual(records[0]['stage'], 'running')
                self.assertIsNotNone(records[0]['calculateCpuMs'])
                self.assertGreaterEqual(records[0]['cancelToFinishMs'], 0)
            finally:
                worker.close()
                release.set()
                worker.thread.join(3)

    def test_new_display_state_still_invalidates_an_older_action(self):
        started, release = Event(), Event()

        def calculate(state):
            started.set()
            self.assertTrue(release.wait(3))
            return {'status': 'ready'}

        with patch('advice_worker.ANALYSIS_DELAY_SECONDS', 60):
            worker = AdviceWorker(calculate)
            try:
                worker.submit('old-action', {'phase': 'playing', 'canAct': True})
                self.assertTrue(started.wait(3))
                worker.submit('new-display', {'phase': 'playing', 'canAct': False})
                release.set()
                records = eventually(worker.take_diagnostics)
                self.assertEqual(records[0]['adviceKey'], 'old-action')
                self.assertEqual(records[0]['outcome'], 'superseded')
                self.assertIsNone(worker.take_result())
                worker.invalidate('new-display')
                records = worker.take_diagnostics()
                self.assertEqual(records[0]['adviceKey'], 'new-display')
                self.assertEqual(records[0]['outcome'], 'invalidated')
                self.assertEqual(records[0]['stage'], 'queued')
            finally:
                worker.close()
                release.set()
                worker.thread.join(3)

    def test_timing_separates_worker_cpu_wall_and_delivery_wait_without_changing_advice(self):
        now = [10.]
        started, release = Event(), Event()
        advice = {'status': 'ready', 'elapsedMs': 17.3, 'candidates': [{'score': 1.5}]}

        def calculate(state):
            started.set()
            self.assertTrue(release.wait(3))
            return advice

        with patch('advice_worker.monotonic', side_effect=lambda: now[0]), \
                patch('advice_worker.thread_time', side_effect=[2., 2.003]):
            worker = AdviceWorker(calculate)
            try:
                worker.submit('key', {})
                self.assertTrue(started.wait(3))
                now[0] = 10.2
                release.set()
                with worker.condition:
                    self.assertTrue(worker.condition.wait_for(lambda: worker.completed is not None, 3))
                now[0] = 10.5
                result = worker.take_result()
                self.assertIs(result['advice'], advice)
                timing = result['diagnostics']
                self.assertEqual(timing['queueMs'], 0)
                self.assertEqual(timing['calculateWallMs'], 200)
                self.assertEqual(timing['calculateCpuMs'], 3)
                self.assertEqual(timing['deliveryWaitMs'], 300)
                self.assertEqual(timing['totalMs'], 500)
                self.assertEqual(worker.take_diagnostics(), [{'kind': 'advisor_timing', **timing}])
                self.assertEqual(worker.take_diagnostics(), [])
            finally:
                worker.close()
                release.set()
                worker.thread.join(3)

    def test_unconsumed_completion_is_diagnosed_when_invalidated_and_storage_is_bounded(self):
        worker = AdviceWorker(lambda state: {'status': 'ready'})
        try:
            worker.submit('completed', {})
            with worker.condition:
                self.assertTrue(worker.condition.wait_for(lambda: worker.completed is not None, 3))
            worker.invalidate()
            record, = worker.take_diagnostics()
            self.assertEqual((record['outcome'], record['stage']), ('invalidated', 'completed'))
            self.assertIsNotNone(record['deliveryWaitMs'])
            self.assertIsNone(worker.take_result())
            with worker.condition:
                for index in range(150):
                    worker.submit(str(index), {'phase': 'playing', 'canAct': False})
                worker.close()
            records = worker.take_diagnostics()
            self.assertEqual(len(records), 128)
            self.assertEqual(records[-1]['outcome'], 'closed')
            self.assertEqual(records[-1]['stage'], 'queued')
            self.assertIsNone(worker.take_result())
        finally:
            worker.close()
            worker.thread.join(3)

    def test_cancellation_callback_does_not_acquire_worker_condition(self):
        started, release, checked = Event(), Event(), Event()
        cancellation = []

        def calculate(state, cancelled, *, ranked_limit):
            started.set()
            if not release.wait(3):
                raise TimeoutError('test did not release calculation')
            cancellation.append(cancelled())
            checked.set()
            return {'status': 'ready'}

        with patch('advisor.advise', side_effect=calculate):
            worker = AdviceWorker()
            try:
                worker.submit('old', {})
                self.assertTrue(started.wait(3))
                with worker.condition:
                    worker.invalidate()
                    release.set()
                    self.assertTrue(checked.wait(3))
                    self.assertEqual(cancellation, [True])
            finally:
                worker.close()
                release.set()
                worker.thread.join(3)
            self.assertFalse(worker.thread.is_alive())
            self.assertIsNone(worker.take_result())

    def test_resubmitting_same_key_cancels_and_drops_the_previous_calculation(self):
        old_started, old_release, new_started, new_release = Event(), Event(), Event(), Event()
        cancellation = []

        def calculate(state, cancelled, *, ranked_limit):
            started, release = (old_started, old_release) if state['step'] == 1 else (new_started, new_release)
            started.set()
            if not release.wait(3):
                raise TimeoutError('test did not release calculation')
            cancellation.append(cancelled())
            return {'status': 'ready', 'step': state['step']}

        with patch('advisor.advise', side_effect=calculate):
            worker = AdviceWorker()
            try:
                worker.submit('same', {'step': 1})
                self.assertTrue(old_started.wait(3))
                worker.submit('same', {'step': 2})
                old_release.set()
                self.assertTrue(new_started.wait(3))
                self.assertEqual(cancellation, [True])
                self.assertIsNone(worker.take_result())
                new_release.set()
                result = eventually(worker.take_result)
                self.assertEqual(result['adviceKey'], 'same')
                self.assertEqual(result['advice'], {'status': 'ready', 'step': 2})
                self.assertEqual(cancellation, [True, False])
            finally:
                worker.close()
                old_release.set()
                new_release.set()
                worker.thread.join(3)
            self.assertFalse(worker.thread.is_alive())

    def test_default_calculation_cancels_superseded_work_and_keeps_latest_snapshot(self):
        started, release = Event(), Event()
        visited, cancellation = [], []

        def calculate(state, cancelled, *, ranked_limit):
            self.assertEqual(ranked_limit, 3)
            visited.append(state['step'])
            cancellation.append(cancelled())
            if state['step'] == 1:
                started.set()
                if not release.wait(3):
                    raise TimeoutError('test did not release old calculation')
                cancellation.append(cancelled())
                return {'status': 'cancelled'}
            return {'status': 'ready', 'step': state['step']}

        with patch('advisor.advise', side_effect=calculate):
            worker = AdviceWorker()
            try:
                worker.submit('one', {'step': 1})
                self.assertTrue(started.wait(3))
                worker.submit('two', {'step': 2})
                worker.submit('three', {'step': 3})
                release.set()
                with worker.condition:
                    self.assertTrue(worker.condition.wait_for(lambda: worker.completed is not None, 3))
                    result = worker.take_result()
                self.assertEqual(result['adviceKey'], 'three')
                self.assertEqual(result['advice'], {'status': 'ready', 'step': 3})
                self.assertEqual(visited, [1, 3])
                self.assertEqual(cancellation, [False, True, False])
                self.assertIsNone(worker.take_result())
            finally:
                worker.close()
                release.set()
                worker.thread.join(3)
            self.assertFalse(worker.thread.is_alive())

    def test_default_calculation_cancels_on_invalidate_and_close(self):
        for action in ('invalidate', 'close'):
            with self.subTest(action=action):
                started, release, finished = Event(), Event(), Event()
                cancellation = []

                def calculate(state, cancelled, *, ranked_limit):
                    self.assertEqual(ranked_limit, 3)
                    cancellation.append(cancelled())
                    started.set()
                    if not release.wait(3):
                        raise TimeoutError('test did not release old calculation')
                    cancellation.append(cancelled())
                    finished.set()
                    return {'status': 'ready'}

                with patch('advisor.advise', side_effect=calculate):
                    worker = AdviceWorker()
                    try:
                        worker.submit('old', {})
                        self.assertTrue(started.wait(3))
                        getattr(worker, action)()
                        release.set()
                        self.assertTrue(finished.wait(3))
                        self.assertEqual(cancellation, [False, True])
                    finally:
                        worker.close()
                        release.set()
                        worker.thread.join(3)
                    self.assertFalse(worker.thread.is_alive())
                    self.assertIsNone(worker.take_result())

    def test_latest_snapshot_wins_and_intermediate_work_is_coalesced(self):
        started, release = Event(), Event()
        visited = []

        def calculate(state):
            visited.append(state['step'])
            if state['step'] == 1:
                started.set()
                self.assertTrue(release.wait(3))
            return {'status': 'ready', 'step': state['step']}

        worker = AdviceWorker(calculate)
        self.addCleanup(worker.close)
        self.addCleanup(release.set)
        state = {'step': 1}
        worker.submit('one', state)
        self.assertTrue(started.wait(3))
        state['step'] = 99
        worker.submit('two', {'step': 2})
        worker.submit('three', {'step': 3})
        release.set()
        result = eventually(worker.take_result)
        self.assertEqual(result['adviceKey'], 'three')
        self.assertEqual(result['advice']['step'], 3)
        self.assertEqual(visited, [1, 3])
        self.assertIsNone(worker.take_result())

    def test_invalidation_discards_inflight_calculation(self):
        started, release, finished = Event(), Event(), Event()

        def calculate(state):
            started.set()
            release.wait(3)
            finished.set()
            return {'status': 'ready'}

        worker = AdviceWorker(calculate)
        self.addCleanup(worker.close)
        self.addCleanup(release.set)
        worker.submit('old', {})
        self.assertTrue(started.wait(3))
        worker.invalidate()
        release.set()
        self.assertTrue(finished.wait(3))
        worker.close()
        worker.thread.join(3)
        self.assertIsNone(worker.take_result())

    def test_failure_is_visible_and_next_board_recovers(self):
        def calculate(state):
            if not state:
                raise ValueError('bad board')
            return {'status': 'waiting'}

        worker = AdviceWorker(calculate)
        self.addCleanup(worker.close)
        worker.submit('bad', {})
        result = eventually(worker.take_result)
        self.assertEqual(result['advice']['status'], 'unavailable')
        self.assertIn('ValueError', result['advice']['error'])
        self.assertIsNot(result['advice'].get('recoverable'), True)
        worker.submit('good', {'ok': True})
        self.assertEqual(eventually(worker.take_result)['advice']['status'], 'waiting')

    def test_budget_marker_reaches_the_exact_window_without_retrying_or_partial_advice(self):
        import advisor
        from test_advisor import state

        checks = 0

        def expire():
            nonlocal checks
            checks += 1
            raise advisor._SearchBudgetExceeded('test budget exhausted')

        worker = AdviceWorker()
        try:
            with patch.object(advisor, '_check_search', side_effect=expire):
                worker.submit('budget-window', state())
                result = eventually(worker.take_result)
            self.assertEqual(checks, 1, 'the same window is not automatically retried')
            self.assertEqual(result['adviceKey'], 'budget-window')
            self.assertEqual(result['advice']['status'], 'unavailable')
            self.assertEqual(result['advice']['reason'], 'search_budget_exceeded')
            self.assertTrue(result['advice']['recoverable'])
            self.assertEqual(result['advice']['candidates'], [])
            self.assertIsNone(result['advice']['best'])
            script = overlay_update(result)
            self.assertIn('"reason": "search_budget_exceeded"', script)
            self.assertIn('"recoverable": true', script)
            self.assertIsNone(worker.take_result())
            worker.submit('next-window', {'phase': 'between_rounds'})
            next_result = eventually(worker.take_result)
            self.assertEqual(next_result['adviceKey'], 'next-window')
            self.assertEqual(next_result['advice']['status'], 'waiting')
        finally:
            worker.close()
            worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())

    def test_overlay_packets_are_keyed_to_the_exact_turn(self):
        event = json.loads((Path(__file__).parent / 'fixtures/turn.json').read_text())
        script = overlay_update(event)
        self.assertIn(f"{event['session']}:{event['serial']}", script)
        self.assertIn('computing', script)
        script = overlay_update({'kind': 'advice', 'adviceKey': 'session:9',
                                 'advice': {'status': 'waiting', 'message': '等待摸牌'}})
        self.assertIn('session:9', script)
        self.assertIn('等待摸牌', script)


if __name__ == '__main__':
    unittest.main()
