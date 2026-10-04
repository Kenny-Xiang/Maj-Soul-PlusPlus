"""One background calculation at a time; retain only the newest board snapshot."""
from copy import deepcopy
from threading import Condition, Thread


class AdviceWorker:
    def __init__(self, calculate=None):
        if calculate is None:
            from advisor import advise
            calculate = advise
        self.calculate = calculate
        self.condition = Condition()
        self.current_key = None
        self.pending = None
        self.completed = None
        self.closed = False
        self.thread = Thread(target=self._run, name="mahjong-advisor", daemon=True)
        self.thread.start()

    def submit(self, key, state):
        with self.condition:
            self.current_key = key
            self.pending = (key, deepcopy(state))
            self.completed = None
            self.condition.notify()

    def invalidate(self):
        with self.condition:
            self.current_key = None
            self.pending = self.completed = None

    def take_result(self):
        with self.condition:
            result, self.completed = self.completed, None
            return result

    def close(self):
        with self.condition:
            self.closed = True
            self.current_key = None
            self.pending = self.completed = None
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                key, state = self.pending
                self.pending = None
            try:
                result = self.calculate(state)
            except Exception as error:
                result = {"status": "unavailable", "message": "评估失败，等待下一次牌局更新",
                          "error": f"{type(error).__name__}: {error}"}
            with self.condition:
                if not self.closed and key == self.current_key:
                    self.completed = {"kind": "advice", "adviceKey": key, "advice": result}
