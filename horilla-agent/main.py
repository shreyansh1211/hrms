"""
Horilla Agent — entry point.

Flow:
  1. Single-instance check — if already running, show "already logged in" dialog and exit.
  2. If a valid 30-day session exists, skip login and go straight to tracking.
  3. Otherwise, show the login window (domain, email, password).
  4. After successful login, hide the window and run tracking in the background
     with a system-tray icon.
  5. Tracking continues until logout or 30-day token expiry.
"""
import logging
import sys
import threading

import single_instance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("horilla_agent")


# --------------------------------------------------------------------------- #
# Check single instance FIRST — before any GUI is created                     #
# --------------------------------------------------------------------------- #

def _already_running_dialog():
    """Show a small 'already logged in' message and exit."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "Horilla Agent is already running.\n\n"
            "Look for the Horilla icon in the system tray (bottom-right corner).",
            "Horilla Agent",
            0x40,  # MB_ICONINFORMATION
        )
    else:
        print("Horilla Agent is already running.")
    sys.exit(0)


if not single_instance.acquire():
    _already_running_dialog()


# --------------------------------------------------------------------------- #
# Import GUI (tkinter)                                                         #
# --------------------------------------------------------------------------- #

import tkinter as tk
from tkinter import messagebox, ttk

import auth
from collector import Collector
from tray import TrayIcon
from uploader import Uploader


# --------------------------------------------------------------------------- #
# Tracking lifecycle                                                           #
# --------------------------------------------------------------------------- #

_collector: Collector | None = None
_uploader: Uploader | None = None
_tray: TrayIcon | None = None


def start_tracking(session: dict):
    global _collector, _uploader, _tray

    policy = auth.fetch_policy(session)
    log.info("policy: %s", policy)

    _uploader = Uploader(session)
    _uploader.start()

    _collector = Collector(session, policy, _uploader)
    _collector.start()

    def on_logout():
        log.info("logout requested")
        auth.clear_session()
        if _collector:
            _collector.stop()
        if _uploader:
            _uploader.stop_event.set()
        single_instance.release()
        sys.exit(0)

    _tray = TrayIcon(session["employee_name"], _collector, on_logout)
    _tray.start()


# --------------------------------------------------------------------------- #
# Login window                                                                 #
# --------------------------------------------------------------------------- #

class LoginWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Horilla Agent — Login")
        self.resizable(False, False)
        self._center()
        self._build()

    def _center(self):
        self.update_idletasks()
        w, h = 420, 340
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self):
        PAD = 24
        BG = "#f8fafc"
        ACCENT = "#017391"
        self.configure(bg=BG)

        # Header
        tk.Label(
            self, text="Horilla Agent", font=("Segoe UI", 18, "bold"),
            bg=BG, fg="#132238",
        ).pack(pady=(PAD, 2))
        tk.Label(
            self, text="Sign in to start tracking your active time",
            font=("Segoe UI", 10), bg=BG, fg="#64748b",
        ).pack(pady=(0, PAD))

        frame = tk.Frame(self, bg=BG)
        frame.pack(padx=PAD, fill="x")

        def field(label, var, show=None):
            tk.Label(frame, text=label, font=("Segoe UI", 10),
                     bg=BG, fg="#132238", anchor="w").pack(fill="x")
            e = tk.Entry(frame, textvariable=var, font=("Segoe UI", 11),
                         relief="solid", bd=1, show=show or "")
            e.pack(fill="x", ipady=6, pady=(2, 10))
            return e

        self._domain = tk.StringVar(value="http://")
        self._email = tk.StringVar()
        self._password = tk.StringVar()

        field("Horilla Domain (e.g. https://hr.yourcompany.com)", self._domain)
        field("Email", self._email)
        field("Password", self._password, show="•")

        self._status = tk.StringVar()
        tk.Label(frame, textvariable=self._status, font=("Segoe UI", 9),
                 bg=BG, fg="#dc2626", wraplength=370, anchor="w").pack(fill="x")

        self._btn = tk.Button(
            frame, text="Sign In", font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="white", relief="flat", cursor="hand2",
            activebackground="#015f78", activeforeground="white",
            command=self._on_login,
        )
        self._btn.pack(fill="x", ipady=8, pady=(8, 0))

        self.bind("<Return>", lambda _: self._on_login())

    def _on_login(self):
        domain = self._domain.get().strip()
        email = self._email.get().strip()
        password = self._password.get()

        if not domain or domain == "http://":
            self._status.set("Please enter the Horilla domain.")
            return
        if not email:
            self._status.set("Please enter your email.")
            return
        if not password:
            self._status.set("Please enter your password.")
            return

        self._status.set("Signing in…")
        self._btn.config(state="disabled")
        self.update()

        def do_login():
            import socket
            device_name = socket.gethostname()
            try:
                session = auth.login(domain, email, password, device_name)
                self.after(0, lambda: self._on_success(session))
            except auth.AuthError as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        threading.Thread(target=do_login, daemon=True).start()

    def _on_success(self, session: dict):
        log.info("logged in as %s", session["employee_name"])
        self.withdraw()          # hide the window — never show it again
        start_tracking(session)
        # Keep tkinter mainloop alive (tray needs it on some platforms)
        self.mainloop_tray()

    def _on_error(self, msg: str):
        self._status.set(msg)
        self._btn.config(state="normal")

    def mainloop_tray(self):
        """After login: hide window, keep mainloop for any future dialogs."""
        # Nothing more to do — tray runs its own message loop on Windows.
        # On other platforms just keep the process alive.
        if sys.platform != "win32":
            self.after(5000, self.mainloop_tray)


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    session = auth.load_session()

    if session:
        # Already have a valid token — skip login, go straight to tracking
        log.info("resuming session for %s", session.get("employee_name"))
        # Need a minimal Tk root so tkinter dialogs (e.g., logout confirm) work
        root = tk.Tk()
        root.withdraw()
        start_tracking(session)
        if sys.platform != "win32":
            root.mainloop()
    else:
        app = LoginWindow()
        app.mainloop()


if __name__ == "__main__":
    main()
