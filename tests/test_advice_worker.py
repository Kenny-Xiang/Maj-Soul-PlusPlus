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
    def test_default_calculation_cancels_superseded_work_and_keeps_latest_snapshot(self):
        started, release = Event(), Event()
        visited, cancellation = [], []

        def calculate(state, cancelled):
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

                def calculate(state, cancelled):
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
        worker.submit('good', {'ok': True})
        self.assertEqual(eventually(worker.take_result)['advice']['status'], 'waiting')

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
