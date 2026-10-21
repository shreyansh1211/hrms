"""
System-tray icon for Infisetu Agent — built with pystray.
"""
import logging
import sys
import threading

log = logging.getLogger("infisetu_agent.tray")

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
    ico = base / "assets" / "infisetu_agent.ico"
    if ico.exists():
        try:
            return Image.open(str(ico)).convert("RGBA")
        except Exception:
            pass
    # Fallback: draw a teal circle with "I"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(1, 115, 145, 255))   # #017391
    draw.text((22, 16), "I", fill=(255, 255, 255, 255))
    return img


# --------------------------------------------------------------------------- #
# TrayIcon                                                                     #
# --------------------------------------------------------------------------- #

class TrayIcon:
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

    def _active_text(self, icon=None, item=None) -> str:
        active = self.collector.today_active if self.collector else 0
        h, rem = divmod(active, 3600)
        return f"Active today: {h}h {rem // 60:02d}m"

    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(
                f"Logged in: {self.employee_name}",
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                self._active_text,
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Logout && Exit",
                self._on_logout,
            ),
        )

    def _on_logout(self, icon, item):
        log.info("LOGOUT | User clicked logout from tray")
        icon.stop()
        self.on_logout()

    def _run(self):
        if not _OK:
            log.error("pystray unavailable — tray icon not started")
            return
        try:
            img = _load_icon()
            self._icon = pystray.Icon(
                name="InfisetuAgent",
                icon=img,
                title=f"Infisetu Agent — {self.employee_name}",
                menu=self._build_menu(),
            )
            log.info("STARTED | Tray icon ready for %s", self.employee_name)
            self._icon.run()
        except Exception as exc:
            log.error("Tray icon crashed: %s", exc)


if not _OK:
    class TrayIcon:                                          # type: ignore[no-redef]
        def __init__(self, employee_name, collector, on_logout, show_window_fn=None):
            self.employee_name  = employee_name
            self.collector      = collector
            self.on_logout      = on_logout
            self.show_window_fn = show_window_fn

        def start(self):
            log.warning("Tray stub started — pystray not available")
