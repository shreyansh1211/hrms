"""
Extracts the current URL from the active browser window.

Supports Chrome, Edge, Firefox, Brave on Windows via UIAutomation.
Falls back gracefully (returns empty string) on any failure.

Reference: infi-time-manager/agent/infitime_agent/collector.py
"""
import sys
import threading
import time

_BROWSER_NAMES = {
    "chrome": "chrome",
    "msedge": "edge",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
}

_cache_lock = threading.Lock()
_cache_url = ""
_cache_app = ""
_cache_ts = 0.0
_CACHE_TTL = 2.0  # seconds


def get_browser_url(app_name: str) -> str:
    """
    Return the URL from the address bar of the active browser.
    Returns "" if the active app is not a supported browser or on error.
    """
    if sys.platform != "win32":
        return ""

    app_lower = (app_name or "").lower()
    if not any(b in app_lower for b in _BROWSER_NAMES):
        return ""

    global _cache_url, _cache_app, _cache_ts
    now = time.monotonic()
    with _cache_lock:
        if app_lower == _cache_app and now - _cache_ts < _CACHE_TTL:
            return _cache_url

    url = _read_url_win()
    with _cache_lock:
        _cache_url = url
        _cache_app = app_lower
        _cache_ts = now
    return url


def _read_url_win() -> str:
    try:
        import uiautomation as auto
        ctrl = auto.GetForegroundControl()
        # Address bar is typically an Edit inside a ToolBar
        edit = ctrl.EditControl(searchDepth=8)
        if edit.Exists(0, 0):
            val = edit.GetValuePattern().Value
            if val and ("." in val or val.startswith("http")):
                return val[:1000]
    except Exception:
        pass
    return ""
