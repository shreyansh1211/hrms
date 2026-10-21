"""
Infisetu Agent — entry point.

Flow:
  1. Single-instance check (socket-based).
       - If already running → signal it to show its window → exit.
       - If first instance  → continue.
  2. If a valid 30-day session exists → skip login → start tracking silently.
  3. Otherwise → show login window → on success → start tracking silently.
  4. Tracking runs silently in the background; tray icon provides status/logout.
"""
import sys

# ── DPI awareness — must happen before any UI is created ─────────────────────
# Prevents blurry windows on Windows displays set to >100% scaling.
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import logging
import threading

import single_instance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("infisetu_agent")


# --------------------------------------------------------------------------- #
# Single-instance check                                                        #
# --------------------------------------------------------------------------- #

if not single_instance.acquire():
    single_instance.signal_existing()
    sys.exit(0)


# --------------------------------------------------------------------------- #
# Imports                                                                      #
# --------------------------------------------------------------------------- #

import tkinter as tk
import auth
from collector import Collector
from tray import TrayIcon
from uploader import Uploader


# --------------------------------------------------------------------------- #
# Palette                                                                      #
# --------------------------------------------------------------------------- #

BG        = "#f0f4f8"
CARD_BG   = "#ffffff"
ACCENT    = "#017391"
ACCENT_H  = "#015f78"
TEXT_DARK = "#132238"
TEXT_MID  = "#475569"
TEXT_HINT = "#94a3b8"
BORDER    = "#e2e8f0"
ERROR_FG  = "#dc2626"


# --------------------------------------------------------------------------- #
# Tracking lifecycle                                                           #
# --------------------------------------------------------------------------- #

_collector: Collector | None = None
_uploader:  Uploader  | None = None
_tray:      TrayIcon  | None = None


def start_tracking(session: dict):
    global _collector, _uploader, _tray

    policy = auth.fetch_policy(session)
    log.info("POLICY | idle=%ss  screenshot=%s–%ss",
             policy.get("idle_threshold_seconds"),
             policy.get("screenshot_interval_min"),
             policy.get("screenshot_interval_max"))

    _uploader = Uploader(session)
    _uploader.start()

    _collector = Collector(session, policy, _uploader)
    _collector.start()

    def on_logout():
        log.info("LOGOUT | Stopping tracking…")
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

class _FocusEntry(tk.Entry):
    def __init__(self, master, **kw):
        self._frame = tk.Frame(master, bg=BORDER, bd=0, highlightthickness=0)
        super().__init__(
            self._frame,
            relief="flat", bd=0, highlightthickness=0,
            bg=CARD_BG, fg=TEXT_DARK,
            insertbackground=ACCENT,
            **kw,
        )
        super().pack(fill="both", expand=True, padx=1, pady=1)
        self.bind("<FocusIn>",  lambda _: self._frame.config(bg=ACCENT))
        self.bind("<FocusOut>", lambda _: self._frame.config(bg=BORDER))

    def grid(self, **kw): self._frame.grid(**kw)
    def pack(self, **kw): self._frame.pack(**kw)


class LoginWindow(tk.Tk):
    W, H = 440, 560

    def __init__(self):
        super().__init__()
        self.title("Infisetu Agent")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._logo_img = None   # keep reference — prevents GC from collecting it
        self._set_icon()
        self._center()
        self._build()

    def _set_icon(self):
        from pathlib import Path
        ico = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "infisetu_agent.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2}")

    def _build(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=30, pady=30)

        card = tk.Frame(outer, bg=CARD_BG, bd=0,
                        highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        card.pack(fill="both", expand=True)

        tk.Frame(card, bg=ACCENT, height=6).pack(fill="x")

        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="both", expand=True, padx=32, pady=(28, 32))

        # ── Logo ─────────────────────────────────────────────────────────────
        self._place_logo(inner)

        tk.Label(inner, text="Infisetu Agent",
                 font=("Segoe UI", 17, "bold"),
                 bg=CARD_BG, fg=TEXT_DARK).pack(pady=(10, 2))
        tk.Label(inner, text="Sign in to start tracking your active time",
                 font=("Segoe UI", 9),
                 bg=CARD_BG, fg=TEXT_MID).pack(pady=(0, 22))

        self._domain   = tk.StringVar(value="http://")
        self._email    = tk.StringVar()
        self._password = tk.StringVar()

        self._d_entry = self._field(inner, "Server URL",    self._domain)
        self._e_entry = self._field(inner, "Email Address", self._email)
        self._p_entry = self._password_field(inner)

        self._d_entry.bind("<Tab>",    lambda _: (self._e_entry.focus(), "break"))
        self._e_entry.bind("<Tab>",    lambda _: (self._p_entry.focus(), "break"))
        self._p_entry.bind("<Return>", lambda _: self._on_login())

        self._status   = tk.StringVar()
        self._btn_text = tk.StringVar(value="Sign In")

        tk.Label(inner, textvariable=self._status,
                 font=("Segoe UI", 9), bg=CARD_BG, fg=ERROR_FG,
                 wraplength=340, justify="left", anchor="w").pack(fill="x", pady=(4, 0))

        self._btn = tk.Button(
            inner,
            textvariable=self._btn_text,
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="white",
            activebackground=ACCENT_H, activeforeground="white",
            relief="flat", bd=0, cursor="hand2",
            command=self._on_login,
        )
        self._btn.pack(fill="x", ipady=10, pady=(14, 0))
        self._btn.bind("<Enter>", lambda _: self._btn.config(bg=ACCENT_H))
        self._btn.bind("<Leave>", lambda _: self._btn.config(
            bg=ACCENT if str(self._btn["state"]) != "disabled" else "#64748b"))

        tk.Label(inner,
                 text="Your data is encrypted and visible\nonly to your HR administrator.",
                 font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_HINT,
                 justify="center").pack(pady=(16, 0))

    def _place_logo(self, parent):
        """Load infisetu_logo.png and display it; fall back to a circle."""
        from pathlib import Path
        logo_path = (
            Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
            / "assets" / "infisetu_logo.png"
        )
        try:
            from PIL import Image, ImageTk
            img = Image.open(str(logo_path)).convert("RGBA")
            img.thumbnail((160, 56), Image.LANCZOS)
            self._logo_img = ImageTk.PhotoImage(img)
            tk.Label(parent, image=self._logo_img, bg=CARD_BG).pack()
        except Exception:
            # Fallback: teal circle with "I"
            c = tk.Canvas(parent, width=52, height=52, bg=CARD_BG,
                          bd=0, highlightthickness=0)
            c.pack()
            c.create_oval(1, 1, 51, 51, fill="#e0f2fe", outline=ACCENT, width=2)
            c.create_text(26, 27, text="I", fill=ACCENT, font=("Segoe UI", 22, "bold"))

    def _field(self, parent, label, var, show=None):
        tk.Label(parent, text=label,
                 font=("Segoe UI", 9, "bold"),
                 bg=CARD_BG, fg=TEXT_MID,
                 anchor="w").pack(fill="x", pady=(0, 3))
        e = _FocusEntry(parent, textvariable=var,
                        font=("Segoe UI", 10), show=show or "")
        e.pack(fill="x", ipady=7, pady=(0, 14))
        return e

    def _password_field(self, parent):
        """Password field with show/hide toggle button."""
        tk.Label(parent, text="Password",
                 font=("Segoe UI", 9, "bold"),
                 bg=CARD_BG, fg=TEXT_MID,
                 anchor="w").pack(fill="x", pady=(0, 3))

        # Outer border frame (same look as _FocusEntry)
        border = tk.Frame(parent, bg=BORDER, bd=0, highlightthickness=0)
        border.pack(fill="x", pady=(0, 14))

        entry = tk.Entry(
            border,
            textvariable=self._password,
            font=("Segoe UI", 10),
            show="●",
            relief="flat", bd=0, highlightthickness=0,
            bg=CARD_BG, fg=TEXT_DARK,
            insertbackground=ACCENT,
        )
        entry.pack(side="left", fill="both", expand=True, padx=(1, 0), ipady=7, pady=1)
        entry.bind("<FocusIn>",  lambda _: border.config(bg=ACCENT))
        entry.bind("<FocusOut>", lambda _: border.config(bg=BORDER))

        self._pw_visible = False

        def toggle():
            self._pw_visible = not self._pw_visible
            entry.config(show="" if self._pw_visible else "●")
            toggle_btn.config(text="Hide" if self._pw_visible else "Show")

        toggle_btn = tk.Button(
            border,
            text="Show",
            font=("Segoe UI", 8),
            bg=CARD_BG, fg=TEXT_MID,
            activebackground=CARD_BG, activeforeground=ACCENT,
            relief="flat", bd=0, cursor="hand2",
            command=toggle,
        )
        toggle_btn.pack(side="right", padx=(0, 6), pady=1)

        return entry

    def _on_login(self):
        domain   = self._domain.get().strip().rstrip("/")
        email    = self._email.get().strip()
        password = self._password.get()
        self._status.set("")

        if not domain or domain in ("http://", "https://"):
            self._status.set("Please enter the server URL.")
            self._d_entry.focus(); return
        if not email:
            self._status.set("Please enter your email address.")
            self._e_entry.focus(); return
        if not password:
            self._status.set("Please enter your password.")
            self._p_entry.focus(); return

        self._btn.config(state="disabled", bg="#64748b")
        self._btn_text.set("Signing in…")
        self.update()

        def do_login():
            import socket
            try:
                session = auth.login(domain, email, password, socket.gethostname())
                self.after(0, lambda: self._on_success(session))
            except auth.AuthError as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        threading.Thread(target=do_login, daemon=True).start()

    def _on_success(self, session: dict):
        log.info("STARTED | Logged in as %s", session["employee_name"])
        self.withdraw()
        start_tracking(session)
        # mainloop keeps running — tray icon is the only UI from here

    def _on_error(self, msg: str):
        self._status.set(msg)
        self._btn.config(state="normal", bg=ACCENT)
        self._btn_text.set("Sign In")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    session = auth.load_session()

    if session:
        log.info("STARTED | Resuming session for %s", session.get("employee_name"))
        root = tk.Tk()
        root.withdraw()
        start_tracking(session)
        root.mainloop()
    else:
        app = LoginWindow()
        app.mainloop()


if __name__ == "__main__":
    main()
