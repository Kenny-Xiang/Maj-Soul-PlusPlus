"""One background calculation at a time; coalesce display-only board updates."""
from collections import deque
from copy import deepcopy
from functools import partial
from threading import Condition, Event, Thread
from time import monotonic, thread_time


ANALYSIS_DELAY_SECONDS = 0.1


class AdviceWorker:
    def __init__(self, calculate=None):
        self.cooperative = calculate is None
        if calculate is None:
            from advisor import advise
            calculate = partial(advise, ranked_limit=3)
        self.calculate = calculate
        self.condition = Condition()
        self.cancel_event = Event()
        self.current_key = None
        self.pending = None
        self.completed = None
        self.active = None
        self.diagnostics = deque(maxlen=128)
        self.closed = False
        self.thread = Thread(target=self._run, name="mahjong-advisor", daemon=True)
        self.thread.start()

    def submit(self, key, state):
        with self.condition:
            if self.closed:
                return
            now = monotonic()
            self._discard('superseded', now)
            self.current_key = key
            analysis = state.get('phase') == 'playing' and state.get('canAct') is False
            self.pending = {'key': key, 'state': deepcopy(state), 'submitted': now,
                            'mode': 'analysis' if analysis else 'action',
                            'ready': now + (ANALYSIS_DELAY_SECONDS if analysis else 0)}
            self.condition.notify()

    def invalidate(self, key=None):
        with self.condition:
            if key is not None and key != self.current_key:
                return
            self._discard('invalidated', monotonic())
            self.current_key = None
            self.condition.notify()

    def take_result(self):
        with self.condition:
            result, self.completed = self.completed, None
            if result is None:
                return None
            packet, task = result
            packet['diagnostics'] = self._record(task, 'delivered', monotonic(), 'completed')
            return packet

    def take_diagnostics(self):
        """Drain on the UI thread; the calculation thread never writes logs."""
        with self.condition:
            records = list(self.diagnostics)
            self.diagnostics.clear()
            return records

    def close(self):
        with self.condition:
            self._discard('closed', monotonic())
            self.closed = True
            self.current_key = None
            self.condition.notify()

    def _discard(self, reason, now):
        self.cancel_event.set()
        if self.active is not None and 'cancelled' not in self.active:
            self.active.update(cancelled=now, outcome=reason)
        if self.pending is not None:
            self._record(self.pending, reason, now, 'queued')
        if self.completed is not None:
            self._record(self.completed[1], reason, now, 'completed')
        self.pending = self.completed = None

    def _record(self, task, outcome, now, stage):
        started, finished = task.get('started'), task.get('finished')
        ms = lambda seconds: round(seconds * 1000, 3)
        record = {
            'adviceKey': task['key'], 'mode': task['mode'], 'outcome': outcome, 'stage': stage,
            # Coalescing is part of queue time, not an additional duration.
            'coalesceMs': ms(min(started if started is not None else now, task['ready']) - task['submitted']),
            'queueMs': ms((started if started is not None else now) - task['submitted']),
            'calculateWallMs': ms(finished - started) if finished is not None else None,
            'calculateCpuMs': task.get('cpuMs'),
            'deliveryWaitMs': ms(now - finished) if stage == 'completed' else None,
            'cancelToFinishMs': ms(max(0, finished - task['cancelled'])) if 'cancelled' in task and finished is not None else None,
            'totalMs': ms(now - task['submitted']),
            'status': task.get('status'), 'reason': task.get('reason'),
        }
        self.diagnostics.append({'kind': 'advisor_timing', **record})
        return record

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                delay = self.pending['ready'] - monotonic()
                if delay > 0:
                    self.condition.wait(delay)
                    continue
                task = self.active = self.pending
                key, state = task['key'], task['state']
                self.pending = None
                cancelled = self.cancel_event = Event()
                task['started'] = monotonic()
            cpu_started = thread_time()
            try:
                if self.cooperative:
                    result = self.calculate(state, cancelled=cancelled.is_set)
                else:
                    result = self.calculate(state)
            except Exception as error:
                result = {"status": "unavailable", "message": "评估失败，等待下一次牌局更新",
                          "error": f"{type(error).__name__}: {error}"}
            cpu_ms = round((thread_time() - cpu_started) * 1000, 3)
            finished = monotonic()
            with self.condition:
                task.update(finished=finished, cpuMs=cpu_ms,
                            status=result.get('status'), reason=result.get('reason'))
                self.active = None
                if not self.closed and key == self.current_key and not cancelled.is_set():
                    packet = {"kind": "advice", "adviceKey": key, "advice": result}
                    self.completed = (packet, task)
                else:
                    self._record(task, task.get('outcome', 'invalidated'), monotonic(), 'running')
                self.condition.notify_all()
