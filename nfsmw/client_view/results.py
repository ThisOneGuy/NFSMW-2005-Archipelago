from collections import deque
from queue import Empty
from threading import Lock


class ViewResults:
    def __init__(self):
        self._values = deque()
        self._lock = Lock()

    def put(self, value, block=True, timeout=None):
        with self._lock:
            if value[0] in ("snapshot", "offline"):
                self._values = deque(
                    entry for entry in self._values if entry[0] not in ("snapshot", "offline")
                )
            self._values.append(value)

    put_nowait = put

    def get_nowait(self):
        with self._lock:
            if not self._values:
                raise Empty
            return self._values.popleft()

    def qsize(self):
        with self._lock:
            return len(self._values)

    def empty(self):
        return self.qsize() == 0
