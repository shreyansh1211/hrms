"""
Horilla Agent — entry point.

Flow:
  1. Single-instance check (socket-based).
       - If already running → signal it to show its log window → exit.
       - If first instance  → continue.
  2. If a valid 30-day session exists → skip login → show log window.
  3. Otherwise → show login window → on success → show log window.
  4. Log window shows live: what is collected + what is uploaded.
  5. Closing the log window hides it; next launch restores it (via IPC).
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

# Global reference so the IPC callback can reach the log window
_log_window = None


# --------------------------------------------------------------------------- #
# Single-instance check                                                        #
# --------------------------------------------------------------------------- #

if not single_instance.acquire():
    # Another instance is running — tell it to show its window, then quit.
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

TERM_BG      = "#0d1117"
TERM_FG      = "#e6edf3"
TERM_ACTIVE  = "#3fb950"
TERM_IDLE    = "#484f58"
TERM_UPLOAD  = "#58a6ff"
TERM_APPUSE  = "#ffa657"
TERM_BROWSER = "#d2a8ff"
TERM_SHOT    = "#ff7b72"
TERM_TIME    = "#6e7681"
TERM_OK      = "#3fb950"
TERM_ERR     = "#f85149"
TERM_HEADER  = "#79c0ff"


# --------------------------------------------------------------------------- #
# Tracking lifecycle                                                           #
# --------------------------------------------------------------------------- #

_collector: Collector | None = None
_uploader:  Uploader  | None = None
_tray:      TrayIcon  | None = None


def start_tracking(session: dict) -> tuple:
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

    def _show_window():
        global _log_window
        if _log_window:
            _log_window.after(0, _log_window._restore)

    _tray = TrayIcon(session["employee_name"], _collector, on_logout,
                     show_window_fn=_show_window)
    _tray.start()

    return _collector, _uploader


# --------------------------------------------------------------------------- #
# Logging handler → writes to LogWindow                                        #
# --------------------------------------------------------------------------- #

class _TkLogHandler(logging.Handler):
    def __init__(self, window):
        super().__init__()
        self._win = window

    def emit(self, record):
        try:
            self._win.append_log(record.levelno, record.getMessage())
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Live log window                                                              #
# --------------------------------------------------------------------------- #

class LogWindow(tk.Toplevel):
    W, H = 780, 560

    def __init__(self, master, session: dict, collector: Collector):
        super().__init__(master)
        self.title("Horilla Agent — Live Tracker")
        self.resizable(True, True)
        self.minsize(600, 400)
        self.configure(bg=TERM_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._session   = session
        self._collector = collector
        self._handler   = None
        self._line_count = 0

        self._set_icon()
        self._center()
        self._build()
        self._install_handler()

        # Register IPC callback — when a second instance starts, restore this window
        single_instance.set_show_callback(self._show_from_any_thread)

        self._tick()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _set_icon(self):
        from pathlib import Path
        ico = Path(__file__).parent / "assets" / "horilla_agent.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2}")

    def _show_from_any_thread(self):
        """Thread-safe: called from IPC listener → schedule on main thread."""
        self.after(0, self._restore)

    def _restore(self):
        """Bring the log window back to front and resume live logging."""
        self._install_handler()   # re-attach so new log lines appear again
        self.deiconify()
        self.lift()
        self.focus_force()

    # ── build ───────────────────────────────────────────────────────────────

    def _build(self):
        # ── teal header ─────────────────────────────────────────────────────
        header = tk.Frame(self, bg=ACCENT, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)

        lf = tk.Frame(header, bg=ACCENT)
        lf.pack(side="left", padx=16, fill="y")
        tk.Label(lf, text="Horilla Agent",
                 font=("Segoe UI", 13, "bold"),
                 bg=ACCENT, fg="white").pack(side="left")

        name = self._session.get("employee_name", "")
        if name:
            tk.Label(lf, text=f"  —  {name}",
                     font=("Segoe UI", 11),
                     bg=ACCENT, fg="#b2e4ef").pack(side="left")

        # Pulsing green dot
        rf = tk.Frame(header, bg=ACCENT)
        rf.pack(side="right", padx=16, fill="y")
        self._dot = tk.Label(rf, text="●", font=("Segoe UI", 12),
                             bg=ACCENT, fg="#22c55e")
        self._dot.pack(side="left")
        tk.Label(rf, text=" Tracking",
                 font=("Segoe UI", 10, "bold"),
                 bg=ACCENT, fg="#dcfce7").pack(side="left")
        self._animate_dot()

        # ── legend strip ────────────────────────────────────────────────────
        leg = tk.Frame(self, bg="#161b22", height=26)
        leg.pack(fill="x")
        leg.pack_propagate(False)
        for text, color in [
            ("ACTIVE", TERM_ACTIVE), ("IDLE", TERM_IDLE),
            ("UPLOAD", TERM_UPLOAD), ("APP USE", TERM_APPUSE),
            ("BROWSER", TERM_BROWSER), ("SCREENSHOT", TERM_SHOT),
            ("✓=ok  ✗=error", TERM_TIME),
        ]:
            tk.Label(leg, text=text, font=("Consolas", 8),
                     bg="#161b22", fg=color).pack(side="left", padx=8, pady=4)

        # ── log text area ────────────────────────────────────────────────────
        txt_frame = tk.Frame(self, bg=TERM_BG)
        txt_frame.pack(fill="both", expand=True)

        vscroll = tk.Scrollbar(txt_frame, bg="#21262d",
                               troughcolor="#161b22",
                               activebackground="#30363d")
        vscroll.pack(side="right", fill="y")

        self._text = tk.Text(
            txt_frame,
            bg=TERM_BG, fg=TERM_FG,
            font=("Consolas", 9),
            relief="flat", bd=0,
            state="disabled",
            wrap="none",
            yscrollcommand=vscroll.set,
            selectbackground="#264f78",
            insertbackground=TERM_FG,
            pady=4, padx=8,
        )
        self._text.pack(fill="both", expand=True)
        vscroll.config(command=self._text.yview)

        hscroll = tk.Scrollbar(self, orient="horizontal",
                               bg="#21262d", troughcolor="#161b22")
        hscroll.pack(fill="x")
        self._text.config(xscrollcommand=hscroll.set)
        hscroll.config(command=self._text.xview)

        # Colour tags
        self._text.tag_config("time",       foreground=TERM_TIME)
        self._text.tag_config("active",     foreground=TERM_ACTIVE,  font=("Consolas", 9, "bold"))
        self._text.tag_config("idle",       foreground=TERM_IDLE)
        self._text.tag_config("upload",     foreground=TERM_UPLOAD,  font=("Consolas", 9, "bold"))
        self._text.tag_config("appuse",     foreground=TERM_APPUSE)
        self._text.tag_config("browser",    foreground=TERM_BROWSER)
        self._text.tag_config("screenshot", foreground=TERM_SHOT)
        self._text.tag_config("ok",         foreground=TERM_OK)
        self._text.tag_config("err",        foreground=TERM_ERR)
        self._text.tag_config("header",     foreground=TERM_HEADER,  font=("Consolas", 9, "bold"))
        self._text.tag_config("normal",     foreground=TERM_FG)

        # ── status bar ───────────────────────────────────────────────────────
        sb = tk.Frame(self, bg="#161b22", height=28)
        sb.pack(fill="x")
        sb.pack_propagate(False)

        self._sv_active = tk.StringVar(value="Active today: 0h 00m")
        self._sv_segs   = tk.StringVar(value="Segments: 0")

        tk.Label(sb, textvariable=self._sv_active,
                 font=("Segoe UI", 9), bg="#161b22", fg=TERM_ACTIVE
                 ).pack(side="left", padx=16, pady=4)
        tk.Label(sb, textvariable=self._sv_segs,
                 font=("Segoe UI", 9), bg="#161b22", fg=TERM_UPLOAD
                 ).pack(side="left", padx=16, pady=4)
        tk.Label(sb,
                 text="Close window to minimise to tray — tracking continues.",
                 font=("Segoe UI", 8), bg="#161b22", fg=TERM_TIME
                 ).pack(side="right", padx=16, pady=4)

        self._write_header()

    def _write_header(self):
        emp    = self._session.get("employee_name", "")
        domain = self._session.get("domain", "")
        lines = [
            "━" * 72,
            f"  Horilla Agent  —  {emp}",
            f"  Server  : {domain}",
            "  Tracks  : keyboard/mouse activity · active app · browser URLs · screenshots",
            "  Uploads : segments every 60s  ·  app/browser totals every 60s",
            "━" * 72,
            "",
        ]
        for line in lines:
            self._append("header", line + "\n")

    # ── log helpers ─────────────────────────────────────────────────────────

    def append_log(self, level: int, msg: str):
        """Thread-safe — schedules the write on the main tkinter thread."""
        self.after(0, lambda: self._write_line(level, msg))

    def _write_line(self, level: int, msg: str):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        upper = msg.upper()

        if "ACTIVE |" in upper:
            tag, label = "active",     "ACTIVE  "
        elif "IDLE   |" in upper or "IDLE |" in upper:
            tag, label = "idle",       "IDLE    "
        elif "UPLOAD |" in upper:
            tag = "ok" if "✓" in msg else ("err" if "✗" in msg else "upload")
            label = "UPLOAD  "
        elif "APP USE |" in upper:
            tag = "ok" if "✓" in msg else ("err" if "✗" in msg else "appuse")
            label = "APP USE "
        elif "BROWSER |" in upper:
            tag = "ok" if "✓" in msg else ("err" if "✗" in msg else "browser")
            label = "BROWSER "
        elif "SCREENSHOT |" in upper:
            tag = "ok" if "✓" in msg else ("err" if "✗" in msg else "screenshot")
            label = "SHOT    "
        elif "STARTED |" in upper or "STOPPED |" in upper or "POLICY |" in upper:
            tag, label = "header", "SYSTEM  "
        elif "LOGOUT |" in upper:
            tag, label = "err", "LOGOUT  "
        elif level >= logging.WARNING:
            tag, label = "err", "WARN    "
        else:
            tag, label = "normal", "INFO    "

        # Strip the known prefix from the message body
        body = msg
        for prefix in (
            "ACTIVE | ", "IDLE   | ", "IDLE | ", "UPLOAD | ",
            "APP USE | ", "BROWSER | ", "SCREENSHOT | ",
            "STARTED | ", "STOPPED | ", "POLICY | ", "LOGOUT | ",
        ):
            if msg.upper().startswith(prefix.upper()):
                body = msg[len(prefix):]
                break

        self._text.config(state="normal")
        self._text.insert("end", f"{ts}  ", "time")
        self._text.insert("end", label, tag)
        self._text.insert("end", " │  ", "time")
        self._text.insert("end", body + "\n", tag)
        self._text.config(state="disabled")

        self._line_count += 1
        if self._line_count > 2000:
            self._text.config(state="normal")
            self._text.delete("1.0", "201.0")
            self._line_count -= 200
            self._text.config(state="disabled")

        self._text.see("end")

    def _append(self, tag: str, text: str):
        self._text.config(state="normal")
        self._text.insert("end", text, tag)
        self._text.config(state="disabled")

    # ── status bar tick ──────────────────────────────────────────────────────

    def _tick(self):
        active = self._collector.today_active if self._collector else 0
        segs   = self._collector.segments_collected if self._collector else 0
        h, rem = divmod(active, 3600)
        self._sv_active.set(f"Active today: {h}h {rem // 60:02d}m")
        self._sv_segs.set(f"Segments: {segs}")
        self.after(5000, self._tick)

    # ── dot pulse ────────────────────────────────────────────────────────────

    def _animate_dot(self, bright=True):
        self._dot.config(fg="#22c55e" if bright else "#166534")
        self.after(900, lambda: self._animate_dot(not bright))

    # ── logging handler ──────────────────────────────────────────────────────

    def _install_handler(self):
        if self._handler:
            return  # already attached
        self._handler = _TkLogHandler(self)
        self._handler.setLevel(logging.INFO)
        logging.getLogger("horilla_agent").addHandler(self._handler)

    def _uninstall_handler(self):
        if self._handler:
            logging.getLogger("horilla_agent").removeHandler(self._handler)
            self._handler = None   # cleared so _install_handler can re-add on restore

    # ── close ────────────────────────────────────────────────────────────────

    def _on_close(self):
        """× button hides to tray — does NOT stop tracking."""
        self._uninstall_handler()
        self.withdraw()


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
    W, H = 440, 530

    def __init__(self):
        super().__init__()
        self.title("Horilla Agent")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._set_icon()
        self._center()
        self._build()

    def _set_icon(self):
        from pathlib import Path
        ico = Path(__file__).parent / "assets" / "horilla_agent.ico"
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

        # Logo
        c = tk.Canvas(inner, width=52, height=52, bg=CARD_BG,
                      bd=0, highlightthickness=0)
        c.pack()
        c.create_oval(1, 1, 51, 51, fill="#e0f2fe", outline=ACCENT, width=2)
        c.create_text(26, 27, text="H", fill=ACCENT, font=("Segoe UI", 22, "bold"))

        tk.Label(inner, text="Horilla Agent",
                 font=("Segoe UI", 17, "bold"),
                 bg=CARD_BG, fg=TEXT_DARK).pack(pady=(10, 2))
        tk.Label(inner, text="Sign in to start tracking your active time",
                 font=("Segoe UI", 9),
                 bg=CARD_BG, fg=TEXT_MID).pack(pady=(0, 22))

        self._domain   = tk.StringVar(value="http://")
        self._email    = tk.StringVar()
        self._password = tk.StringVar()

        self._d_entry = self._field(inner, "Horilla Server URL", self._domain)
        self._e_entry = self._field(inner, "Email Address",      self._email)
        self._p_entry = self._field(inner, "Password",           self._password, show="●")

        self._d_entry.bind("<Tab>",    lambda _: (self._e_entry.focus(),  "break"))
        self._e_entry.bind("<Tab>",    lambda _: (self._p_entry.focus(),  "break"))
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

    def _field(self, parent, label, var, show=None):
        tk.Label(parent, text=label,
                 font=("Segoe UI", 9, "bold"),
                 bg=CARD_BG, fg=TEXT_MID,
                 anchor="w").pack(fill="x", pady=(0, 3))
        e = _FocusEntry(parent, textvariable=var,
                        font=("Segoe UI", 10), show=show or "")
        e.pack(fill="x", ipady=7, pady=(0, 14))
        return e

    def _on_login(self):
        domain   = self._domain.get().strip().rstrip("/")
        email    = self._email.get().strip()
        password = self._password.get()
        self._status.set("")

        if not domain or domain in ("http://", "https://"):
            self._status.set("Please enter the Horilla server URL.")
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
        collector, _ = start_tracking(session)
        global _log_window
        _log_window = LogWindow(self, session, collector)

    def _on_error(self, msg: str):
        self._status.set(msg)
        self._btn.config(state="normal", bg=ACCENT)
        self._btn_text.set("Sign In")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    global _log_window

    session = auth.load_session()

    if session:
        log.info("STARTED | Resuming session for %s", session.get("employee_name"))
        root = tk.Tk()
        root.withdraw()
        collector, _ = start_tracking(session)
        _log_window = LogWindow(root, session, collector)
        root.mainloop()
    else:
        app = LoginWindow()
        app.mainloop()


if __name__ == "__main__":
    main()
