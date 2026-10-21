"""
System-tray icon for Horilla Agent — built with pystray.

pystray is cross-platform and handles all Win32 Shell_NotifyIcon details
correctly, making the icon appear reliably in the notification area on
Windows 10 / 11 (hidden-icons overflow area, right side of taskbar).

Right-click menu:
  Logged in: <name>       ← grayed header
  Active today: Xh Ym     ← live-updated
  ─────────────────────
  Open Tracker Window
  ─────────────────────
  Logout && Exit
"""
import logging
import sys
import threading
import time

log = logging.getLogger("horilla_agent.tray")

try:
    import pystray
    from PIL import Image, ImageDraw
    _OK = True
except ImportError:
    _OK = False
    log.warning("pystray / Pillow not installed — tray icon disabled. "
                "Run: pip install pystray pillow")


# --------------------------------------------------------------------------- #
# Icon image                                                                   #
# --------------------------------------------------------------------------- #

def _load_icon() -> "Image.Image":
    """Load the .ico asset, or generate a teal fallback circle."""
    from pathlib import Path
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    ico = base / "assets" / "horilla_agent.ico"
    if ico.exists():
        try:
            return Image.open(str(ico)).convert("RGBA")
        except Exception:
            pass
    # Fallback: draw a teal circle with "H"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(1, 115, 145, 255))   # #017391
    draw.text((20, 16), "H", fill=(255, 255, 255, 255))
    return img


# --------------------------------------------------------------------------- #
# TrayIcon                                                                     #
# --------------------------------------------------------------------------- #

class TrayIcon:
    """
    Wraps a pystray.Icon running in a daemon thread.

    Parameters
    ----------
    employee_name   : display name shown in the tray menu
    collector       : Collector instance (for today_active)
    on_logout       : callable — called when user chooses Logout
    show_window_fn  : callable — called when user chooses Open Tracker Window
    """

    def __init__(
        self,
        employee_name: str,
        collector,
        on_logout,
        show_window_fn=None,
    ):
        self.employee_name  = employee_name
        self.collector      = collector
        self.on_logout      = on_logout
        self.show_window_fn = show_window_fn
        self._icon: "pystray.Icon | None" = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="tray"
        )

    def start(self):
        self._thread.start()

    # ── menu helpers ─────────────────────────────────────────────────────────

    def _active_text(self, icon=None, item=None) -> str:
        active = self.collector.today_active if self.collector else 0
        h, rem = divmod(active, 3600)
        return f"Active today: {h}h {rem // 60:02d}m"

    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            # Header — grayed, shows username
            pystray.MenuItem(
                f"Logged in: {self.employee_name}",
                None,
                enabled=False,
            ),
            # Live active-time — text is a callable so it refreshes on open
            pystray.MenuItem(
                self._active_text,
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Open Tracker Window",
                self._on_show,
                default=True,   # double-click action
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Logout && Exit",
                self._on_logout,
            ),
        )

    # ── callbacks ────────────────────────────────────────────────────────────

    def _on_show(self, icon, item):
        if self.show_window_fn:
            self.show_window_fn()

    def _on_logout(self, icon, item):
        log.info("LOGOUT | User clicked logout from tray")
        icon.stop()
        self.on_logout()

    # ── run loop ─────────────────────────────────────────────────────────────

    def _run(self):
        if not _OK:
            log.error("pystray unavailable — tray icon not started")
            return

        try:
            img = _load_icon()

            self._icon = pystray.Icon(
                name="HorillaAgent",
                icon=img,
                title=f"Horilla Agent — {self.employee_name}",
                menu=self._build_menu(),
            )

            log.info("STARTED | Tray icon ready for %s", self.employee_name)

            # pystray.Icon.run() blocks until icon.stop() is called
            self._icon.run()

        except Exception as exc:
            log.error("Tray icon crashed: %s", exc)


# --------------------------------------------------------------------------- #
# Non-pystray stub (should not normally be reached)                           #
# --------------------------------------------------------------------------- #

if not _OK:
    # Re-define TrayIcon as a no-op so the rest of the code still runs
    class TrayIcon:                                          # type: ignore[no-redef]
        def __init__(self, employee_name, collector, on_logout, show_window_fn=None):
            self.employee_name  = employee_name
            self.collector      = collector
            self.on_logout      = on_logout
            self.show_window_fn = show_window_fn

        def start(self):
            log.warning("Tray stub started — pystray not available")
