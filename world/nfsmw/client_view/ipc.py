import json
from pathlib import Path
import queue
import socket
import threading
from .state import desktop_state_directory
from .results import ViewResults


def request_owner(action, session_path=None, timeout=1.0):
    path = (
        Path(session_path) if session_path else desktop_state_directory() / "desktop_session.json"
    )
    session = json.loads(path.read_text(encoding="utf-8"))
    port, token = session["port"], session["token"]
    if (
        not isinstance(port, int)
        or not 0 < port < 65536
        or not isinstance(token, str)
        or len(token) != 64
    ):
        raise ValueError("No active NFSMW connection client.")
    payload = {**action, "token": token}
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        with connection.makefile("rb") as stream:
            raw = stream.readline(4 * 1024 * 1024)
        if not raw.endswith(b"\n"):
            raise ValueError("The client view response was incomplete.")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("Invalid client view response.")
    return response


class ViewWorker:
    def __init__(self, request=request_owner):
        self.request = request
        self.actions = queue.Queue(maxsize=32)
        self.results = ViewResults()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.run, name="NFSMW client view", daemon=True)

    def start(self):
        self.thread.start()

    def offer(self, value):
        self.results.put_nowait(value)

    def run(self):
        while not self.stop.is_set():
            try:
                while not self.stop.is_set():
                    try:
                        action = self.actions.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        result = self.request(action)
                        result.setdefault("operation", action.get("action"))
                        self.offer(("action", result))
                    except (OSError, ValueError, KeyError):
                        self.offer(
                            (
                                "action",
                                {
                                    "ok": False,
                                    "operation": action.get("action"),
                                    "error": "Connection client is not running.",
                                },
                            )
                        )
                if self.stop.is_set():
                    break
                result = self.request({"action": "snapshot"})
                if result.get("ok") and isinstance(result.get("snapshot"), dict):
                    self.offer(("snapshot", result["snapshot"]))
                else:
                    self.offer(("offline", None))
            except (OSError, ValueError, KeyError):
                self.offer(("offline", None))
            self.wake.wait(0.8)
            self.wake.clear()

    def submit(self, action):
        try:
            self.actions.put_nowait(action)
        except queue.Full:
            return False
        self.wake.set()
        return True

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)
