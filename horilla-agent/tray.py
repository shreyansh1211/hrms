"""
Windows system-tray icon for the Horilla Agent.

Shows the employee name and today's active time in the tooltip.
Right-click menu:
  • Logged in as: <name>   (grayed header)
  ─────────────────────────────
  • Open Tracker Window
  ─────────────────────────────
  • Logout && Exit

On non-Windows (dev): falls back to a no-op stub.
"""
import logging
import sys
import threading

log = logging.getLogger("horilla_agent.tray")


# --------------------------------------------------------------------------- #
# Windows implementation                                                       #
# --------------------------------------------------------------------------- #

if sys.platform == "win32":
    import win32api
    import win32con
    import win32gui

    WM_TRAY   = win32con.WM_USER + 20
    ID_SHOW   = 1000
    ID_LOGOUT = 1002

    NIIF_INFO               = 0x00000001
    NIF_INFO                = 0x00000010
    NOTIFYICON_VERSION_4    = 4
    NIM_SETVERSION          = 0x00000004

    class TrayIcon:
        def __init__(self, employee_name: str, collector, on_logout, show_window_fn=None):
            self.employee_name  = employee_name
            self.collector      = collector
            self.on_logout      = on_logout
            self.show_window_fn = show_window_fn
            self.hwnd           = None
            self._hicon         = None
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="tray"
            )

        def start(self):
            self._thread.start()

        # ── icon ────────────────────────────────────────────────────────────

        def _icon(self):
            if self._hicon is None:
                from pathlib import Path
                base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
                ico = base / "assets" / "horilla_agent.ico"
                loaded = False
                if ico.exists():
                    try:
                        self._hicon = win32gui.LoadImage(
                            0, str(ico), win32con.IMAGE_ICON, 16, 16,
                            win32con.LR_LOADFROMFILE,
                        )
                        loaded = True
                    except Exception as e:
                        log.warning("Could not load .ico: %s", e)
                if not loaded:
                    self._hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            return self._hicon

        # ── tooltip (max 127 chars) ──────────────────────────────────────────

        def _tooltip(self) -> str:
            active = self.collector.today_active if self.collector else 0
            h, rem = divmod(active, 3600)
            return f"Horilla Agent — {self.employee_name} — Active: {h}h {rem // 60:02d}m"

        # ── tray notification ────────────────────────────────────────────────

        def _notify(self, action):
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            win32gui.Shell_NotifyIcon(
                action,
                (self.hwnd, 0, flags, WM_TRAY, self._icon(), self._tooltip()[:127]),
            )

        # ── window procedure ────────────────────────────────────────────────

        def _wndproc(self, hwnd, msg, wparam, lparam):
            if msg == WM_TRAY and lparam in (
                win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP
            ):
                menu = win32gui.CreatePopupMenu()

                # Header: logged-in username (grayed, not clickable)
                win32gui.AppendMenu(
                    menu,
                    win32con.MF_STRING | win32con.MF_GRAYED,
                    0,
                    f"Logged in as: {self.employee_name}",
                )

                # Active-time info (grayed)
                active = self.collector.today_active if self.collector else 0
                h, rem = divmod(active, 3600)
                win32gui.AppendMenu(
                    menu,
                    win32con.MF_STRING | win32con.MF_GRAYED,
                    0,
                    f"Active today: {h}h {rem // 60:02d}m",
                )

                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

                # Open tracker window
                win32gui.AppendMenu(
                    menu, win32con.MF_STRING, ID_SHOW, "Open Tracker Window"
                )

                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

                # Logout
                win32gui.AppendMenu(
                    menu, win32con.MF_STRING, ID_LOGOUT, "Logout && Exit"
                )

                win32gui.SetForegroundWindow(hwnd)
                x, y = win32gui.GetCursorPos()
                cmd = win32gui.TrackPopupMenu(
                    menu, win32con.TPM_RETURNCMD, x, y, 0, hwnd, None
                )

                if cmd == ID_SHOW:
                    if self.show_window_fn:
                        self.show_window_fn()

                elif cmd == ID_LOGOUT:
                    confirm = win32api.MessageBox(
                        0,
                        "Are you sure you want to logout and stop tracking?",
                        "Horilla Agent — Logout",
                        win32con.MB_YESNO | win32con.MB_ICONQUESTION,
                    )
                    if confirm == win32con.IDYES:
                        self.on_logout()
                        win32gui.PostQuitMessage(0)

            elif msg == win32con.WM_TIMER:
                self._notify(win32gui.NIM_MODIFY)

            elif msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)

            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        # ── run ─────────────────────────────────────────────────────────────

        def _show_balloon(self, title: str, text: str):
            """Show a balloon/toast notification from the tray icon."""
            try:
                import ctypes
                # NIF_INFO flag lets Shell_NotifyIcon show a balloon
                flags = (win32gui.NIF_ICON | win32gui.NIF_MESSAGE
                         | win32gui.NIF_TIP | NIF_INFO)
                win32gui.Shell_NotifyIcon(
                    win32gui.NIM_MODIFY,
                    (
                        self.hwnd, 0, flags, WM_TRAY,
                        self._icon(),
                        self._tooltip()[:127],
                        text[:255],      # balloon body
                        3000,            # ms to show
                        title[:63],      # balloon title
                        NIIF_INFO,
                    ),
                )
            except Exception:
                pass  # balloon is informational only

        def _run(self):
            wc = win32gui.WNDCLASS()
            wc.hInstance       = win32api.GetModuleHandle(None)
            wc.lpszClassName   = "HorillaAgentTray"
            wc.lpfnWndProc     = self._wndproc
            try:
                win32gui.RegisterClass(wc)
            except Exception:
                pass  # already registered (process restart without cleanup)
            try:
                self.hwnd = win32gui.CreateWindow(
                    wc.lpszClassName, "Horilla Agent",
                    0, 0, 0, 0, 0, 0, 0, wc.hInstance, None,
                )
            except Exception as exc:
                log.error("CreateWindow failed: %s", exc)
                return

            # Add icon to tray
            self._notify(win32gui.NIM_ADD)

            # NIM_SETVERSION enables modern (Vista+) notification behaviour
            # so the icon appears reliably in the taskbar notification area
            try:
                win32gui.Shell_NotifyIcon(
                    NIM_SETVERSION,
                    (self.hwnd, 0, 0, 0, 0, "", NOTIFYICON_VERSION_4),
                )
            except Exception:
                pass

            # Startup balloon — draws user's attention to the icon
            import threading as _t
            _t.Timer(
                1.5,
                lambda: self._show_balloon(
                    "Horilla Agent",
                    f"Tracking active time for {self.employee_name}. "
                    "Right-click this icon for options.",
                ),
            ).start()

            win32gui.SetTimer(self.hwnd, 1, 30_000, None)
            win32gui.PumpMessages()
            self._notify(win32gui.NIM_DELETE)


# --------------------------------------------------------------------------- #
# Non-Windows stub (dev / CI)                                                  #
# --------------------------------------------------------------------------- #

else:
    class TrayIcon:
        def __init__(self, employee_name: str, collector, on_logout, show_window_fn=None):
            self.employee_name  = employee_name
            self.collector      = collector
            self.on_logout      = on_logout
            self.show_window_fn = show_window_fn
            log.info("TrayIcon stub: running on non-Windows platform")

        def start(self):
            log.info("Tray stub started for %s", self.employee_name)
