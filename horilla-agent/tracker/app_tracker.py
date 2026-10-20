"""
Tracks the currently active application and window title.

Windows: uses win32gui / pywin32.
macOS  : uses AppKit (dev only).
"""
import sys
import time


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
