"""
Low-level keyboard and mouse activity monitor.

Uses pynput (cross-platform) to count keystrokes / clicks / moves.

Idle detection on Windows uses GetLastInputInfo() directly from the OS
(ctypes / user32) — this is far more reliable than pynput-based timing
because it works even when pynput listeners are slow or the window loses
focus.  On non-Windows the pynput timestamp is the fallback.

INJECTED input (from automation/jigglers) is ignored on Windows because
GetLastInputInfo already filters synthetic input in most cases.
"""
import sys
import threading
import time

try:
    from pynput import keyboard, mouse
    _PYNPUT = True
except Exception:
    _PYNPUT = False


# --------------------------------------------------------------------------- #
# Windows OS-level last-input query                                           #
# --------------------------------------------------------------------------- #

if sys.platform == "win32":
    import ctypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    def _win32_idle_seconds() -> float | None:
        """Return seconds since the last real user input, or None on error."""
        try:
            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                return None
            tick_now = ctypes.windll.kernel32.GetTickCount()
            elapsed_ms = (tick_now - lii.dwTime) & 0xFFFFFFFF  # handle tick wrap
            return elapsed_ms / 1000.0
        except Exception:
            return None
else:
    def _win32_idle_seconds() -> float | None:
        return None


# --------------------------------------------------------------------------- #
# InputMonitor                                                                 #
# --------------------------------------------------------------------------- #

class InputMonitor:
    """
    Tracks whether the user is active (keyboard/mouse).

    is_active() — True if the user had input within idle_threshold seconds.
    consume_counts() — return and reset key/click/move counters.
    """

    def __init__(self, idle_threshold: int = 180):
        self.idle_threshold = idle_threshold
        self._last_input = time.monotonic()
        self._keys   = 0
        self._clicks = 0
        self._moves  = 0
        self._lock = threading.Lock()
        self._listeners: list = []

    # ── pynput callbacks (count only) ────────────────────────────────────────

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
            if t - self._last_input > 0.05:   # jiggler heuristic
                self._last_input = t
                self._moves += 1

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        if not _PYNPUT:
            return
        try:
            kb = keyboard.Listener(on_press=self._on_key)
            ms = mouse.Listener(on_click=self._on_click, on_move=self._on_move)
            kb.start()
            ms.start()
            self._listeners = [kb, ms]
        except Exception:
            pass  # pynput may fail in restricted environments; idle via OS API

    def stop(self):
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._listeners = []

    # ── state queries ────────────────────────────────────────────────────────

    def idle_seconds(self) -> float:
        """
        Return seconds elapsed since the last real user input.

        Uses GetLastInputInfo on Windows (most reliable); falls back to the
        pynput-tracked timestamp on other platforms.
        """
        s = _win32_idle_seconds()
        if s is not None:
            return s
        with self._lock:
            return max(0.0, time.monotonic() - self._last_input)

    def is_active(self) -> bool:
        """True if idle_seconds() < idle_threshold."""
        return self.idle_seconds() < self.idle_threshold

    @property
    def last_input_monotonic(self) -> float:
        """Monotonic timestamp of last recorded input (pynput path only)."""
        with self._lock:
            return self._last_input

    def consume_counts(self) -> dict:
        """Return and reset key / click / move counts since last call."""
        with self._lock:
            c = {"keys": self._keys, "clicks": self._clicks, "moves": self._moves}
            self._keys = self._clicks = self._moves = 0
        return c
