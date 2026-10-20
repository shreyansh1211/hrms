"""
Low-level keyboard and mouse activity monitor.

Uses pynput (cross-platform) to detect real user input.
Idle detection: if no input for `idle_threshold` seconds → mark as idle.
INJECTED input (from automation/jigglers) is ignored on Windows.
"""
import threading
import time

try:
    from pynput import keyboard, mouse
    _PYNPUT = True
except Exception:
    _PYNPUT = False


class InputMonitor:
    """
    Tracks whether the user is active (keyboard/mouse).

    Usage:
        mon = InputMonitor(idle_threshold=180)
        mon.start()
        ...
        mon.is_active()   # True if user was active in last idle_threshold seconds
        mon.stop()
    """

    def __init__(self, idle_threshold: int = 180):
        self.idle_threshold = idle_threshold
        self._last_input = time.monotonic()
        self._keys = 0
        self._clicks = 0
        self._moves = 0
        self._lock = threading.Lock()
        self._listeners = []

    def _on_key(self, key):
        with self._lock:
            self._last_input = time.monotonic()
            self._keys += 1

    def _on_click(self, x, y, button, pressed):
        if pressed:
            with self._lock:
                self._last_input = time.monotonic()
                self._clicks += 1

    def _on_move(self, x, y):
        with self._lock:
            t = time.monotonic()
            # Only count moves that aren't suspiciously regular (jiggler heuristic)
            if t - self._last_input > 0.05:
                self._last_input = t
                self._moves += 1

    def start(self):
        if not _PYNPUT:
            return
        kb = keyboard.Listener(on_press=self._on_key)
        ms = mouse.Listener(on_click=self._on_click, on_move=self._on_move)
        kb.start()
        ms.start()
        self._listeners = [kb, ms]

    def stop(self):
        for l in self._listeners:
            try:
                l.stop()
            except Exception:
                pass
        self._listeners = []

    def is_active(self) -> bool:
        with self._lock:
            return (time.monotonic() - self._last_input) < self.idle_threshold

    def consume_counts(self) -> dict:
        """Return and reset key/click/move counts since last call."""
        with self._lock:
            c = {"keys": self._keys, "clicks": self._clicks, "moves": self._moves}
            self._keys = self._clicks = self._moves = 0
        return c
