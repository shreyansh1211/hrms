"""
Ensure only one instance of the agent runs at a time.

Uses a TCP socket bound to localhost:48291 as the lock.
  - First instance:  binds the port → success → starts IPC listener thread.
  - Second instance: port already bound → sends "SHOW" signal to first instance
                     (which brings its log window back to front) → caller exits.

This is cross-platform and avoids Windows named-mutex quirks.
"""
import socket
import threading

_PORT = 48291
_server: socket.socket | None = None
_show_callback = None   # set by main.py after the log window is created


def set_show_callback(fn):
    """Register a callable that is invoked (on the main thread) when a second
    instance asks to show the window."""
    global _show_callback
    _show_callback = fn


def acquire() -> bool:
    """Try to become the single running instance.
    Returns True  → we are the only instance (lock acquired).
    Returns False → another instance is already running.
    """
    global _server
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", _PORT))
        sock.listen(5)
        _server = sock
        t = threading.Thread(target=_ipc_listener, daemon=True, name="ipc")
        t.start()
        return True
    except OSError:
        sock.close()
        return False


def signal_existing():
    """Tell the already-running instance to show its log window.
    Call this from the second instance before exiting.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", _PORT))
        s.sendall(b"SHOW")
        s.close()
    except Exception:
        pass  # first instance may have crashed — silently ignore


def release():
    global _server
    if _server:
        try:
            _server.close()
        except Exception:
            pass
        _server = None


def _ipc_listener():
    """Background thread: accept one-shot connections and handle commands."""
    while _server:
        try:
            conn, _ = _server.accept()
            try:
                data = conn.recv(32).decode(errors="ignore").strip()
            finally:
                conn.close()
            if data == "SHOW" and _show_callback:
                _show_callback()
        except Exception:
            break
