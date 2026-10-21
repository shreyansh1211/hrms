"""
Tracks the currently active application and window title.

Windows: uses win32gui / pywin32.
macOS  : uses AppKit (dev only).

Also provides WindowWatcher — a background thread that polls every 100 ms
for focus changes and fires an on_event callback with the actual duration
the previous window was in focus.
"""
import sys
import threading
import time


# --------------------------------------------------------------------------- #
# Privacy: messaging / social apps — suppress window title                    #
# --------------------------------------------------------------------------- #

MESSAGING_APPS = {
    "whatsapp", "telegram", "signal", "discord",
    "teams", "zoom", "skype", "messenger", "viber",
    "line", "wechat", "messages", "facetime",
    "slack",  # workplace chat — keep as messaging (titles show channel/DM names)
}


def should_hide_title(app_name: str) -> bool:
    """Return True to suppress window title for this app (privacy)."""
    app_lower = (app_name or "").lower()
    return any(m in app_lower for m in MESSAGING_APPS)


# --------------------------------------------------------------------------- #
# Active window query                                                          #
# --------------------------------------------------------------------------- #

def get_active_window() -> dict:
    """
    Returns {"app": str, "title": str}.
    Returns empty strings on failure.
    """
    try:
        if sys.platform == "win32":
            return _windows_active()
        elif sys.platform == "darwin":
            return _mac_active()
        return {"app": "", "title": ""}
    except Exception:
        return {"app": "", "title": ""}


# --------------------------------------------------------------------------- #
# Windows                                                                      #
# --------------------------------------------------------------------------- #

def _windows_active() -> dict:
    import win32gui
    import win32process
    import psutil

    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        app = proc.name().replace(".exe", "")
    except Exception:
        app = ""
    return {"app": app, "title": title}


# --------------------------------------------------------------------------- #
# macOS (dev / testing only)                                                   #
# --------------------------------------------------------------------------- #

def _mac_active() -> dict:
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication().localizedName() or ""
    except Exception:
        app = ""
    return {"app": app, "title": ""}


# --------------------------------------------------------------------------- #
# WindowWatcher — real-time focus-change detection                             #
# --------------------------------------------------------------------------- #

POLL_INTERVAL = 0.10   # 100 ms between polls
MIN_DURATION_MS = 20   # ignore focus flickers shorter than 20 ms


class WindowWatcher:
    """
    Background thread that polls the active window every 100 ms.

    When the focused app/title changes, calls:
        on_event(app, title, start_ts, end_ts, duration_ms)

    where start_ts / end_ts are epoch floats and duration_ms is an int.

    Also supports flush_current() — emit an event for the current
    window without changing state (used by the periodic flush cycle).
    """

    def __init__(self, on_event):
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="window_watcher"
        )
        self._lock = threading.Lock()
        self._current_app = ""
        self._current_title = ""
        self._current_start = 0.0

    def start(self):
        now = time.time()
        win = get_active_window()
        with self._lock:
            self._current_app = win.get("app", "")
            self._current_title = win.get("title", "")
            self._current_start = now
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get_current(self) -> dict:
        with self._lock:
            return {"app": self._current_app, "title": self._current_title}

    def flush_current(self):
        """Emit an event for the elapsed time in the current window, reset start."""
        now = time.time()
        with self._lock:
            app = self._current_app
            title = self._current_title
            start = self._current_start
            self._current_start = now

        duration_ms = int((now - start) * 1000)
        if app and duration_ms >= MIN_DURATION_MS:
            self._on_event(app, title, start, now, duration_ms)

    def _run(self):
        while not self._stop.wait(POLL_INTERVAL):
            try:
                win = get_active_window()
                app = win.get("app", "")
                title = win.get("title", "")

                with self._lock:
                    changed = (app != self._current_app or title != self._current_title)
                    if not changed:
                        continue
                    now = time.time()
                    prev_app = self._current_app
                    prev_title = self._current_title
                    prev_start = self._current_start
                    self._current_app = app
                    self._current_title = title
                    self._current_start = now

                duration_ms = int((now - prev_start) * 1000)
                if prev_app and duration_ms >= MIN_DURATION_MS:
                    self._on_event(prev_app, prev_title, prev_start, now, duration_ms)
            except Exception:
                pass
