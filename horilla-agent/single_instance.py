"""
Ensure only one instance of the agent runs at a time.

On Windows: uses a named mutex.
On other platforms (dev): uses a lock file.
"""
import sys


if sys.platform == "win32":
    import ctypes

    _MUTEX = None

    def acquire() -> bool:
        """Returns True if this is the only instance, False if another is already running."""
        global _MUTEX
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "HorillaAgentSingleInstance")
        last_err = ctypes.windll.kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        return last_err != ERROR_ALREADY_EXISTS

    def release() -> None:
        global _MUTEX
        if _MUTEX:
            ctypes.windll.kernel32.CloseHandle(_MUTEX)
            _MUTEX = None

else:
    import fcntl
    import os
    from pathlib import Path

    _LOCK_FILE = Path("/tmp/horilla_agent.lock")
    _FD = None

    def acquire() -> bool:
        global _FD
        try:
            _FD = open(_LOCK_FILE, "w")
            fcntl.flock(_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _FD.write(str(os.getpid()))
            _FD.flush()
            return True
        except OSError:
            return False

    def release() -> None:
        global _FD
        if _FD:
            fcntl.flock(_FD, fcntl.LOCK_UN)
            _FD.close()
            _LOCK_FILE.unlink(missing_ok=True)
            _FD = None
