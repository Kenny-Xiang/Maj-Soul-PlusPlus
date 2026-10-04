"""Deterministic concurrency checks: superseded boards must never reach the overlay."""
import json
from pathlib import Path
from threading import Event
import time
import unittest

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
