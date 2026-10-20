"""
Windows system-tray icon for the Horilla Agent.

Shows the employee name and today's active time in the tooltip.
Right-click menu: "About" and "Logout".
The window is never shown after login — the tray is the only UI.

On non-Windows (dev): falls back to a no-op stub so the rest of the
code can run without pywin32.
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

    WM_TRAY = win32con.WM_USER + 20
    ID_ABOUT = 1001
    ID_LOGOUT = 1002

    class TrayIcon:
        def __init__(self, employee_name: str, collector, on_logout):
            self.employee_name = employee_name
            self.collector = collector
            self.on_logout = on_logout
            self.hwnd = None
            self._hicon = None
            self._thread = threading.Thread(target=self._run, daemon=True, name="tray")

        def start(self):
            self._thread.start()

        def _icon(self):
            if self._hicon is None:
                import os, sys
                from pathlib import Path
                base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
                ico = base / "assets" / "horilla_agent.ico"
                try:
                    self._hicon = win32gui.LoadImage(
                        0, str(ico), win32con.IMAGE_ICON, 16, 16,
                        win32con.LR_LOADFROMFILE,
                    )
                except Exception:
                    self._hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            return self._hicon

        def _tooltip(self) -> str:
            active = self.collector.today_active if self.collector else 0
            h, rem = divmod(active, 3600)
            return f"Horilla Agent — {self.employee_name} — Active: {h}h {rem // 60:02d}m"

        def _notify(self, action):
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            win32gui.Shell_NotifyIcon(
                action,
                (self.hwnd, 0, flags, WM_TRAY, self._icon(), self._tooltip()[:127]),
            )

        def _wndproc(self, hwnd, msg, wparam, lparam):
            if msg == WM_TRAY and lparam in (
                win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP
            ):
                menu = win32gui.CreatePopupMenu()
                win32gui.AppendMenu(
                    menu, win32con.MF_STRING | win32con.MF_GRAYED,
                    0, self._tooltip()
                )
                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
                win32gui.AppendMenu(menu, win32con.MF_STRING, ID_ABOUT, "About Horilla Agent")
                win32gui.AppendMenu(menu, win32con.MF_STRING, ID_LOGOUT, "Logout && Exit")
                win32gui.SetForegroundWindow(hwnd)
                x, y = win32gui.GetCursorPos()
                cmd = win32gui.TrackPopupMenu(
                    menu, win32con.TPM_RETURNCMD, x, y, 0, hwnd, None
                )
                if cmd == ID_ABOUT:
                    win32api.MessageBox(
                        0,
                        (
                            "Horilla Agent is tracking your active desk time.\n\n"
                            "It records:\n"
                            "  • When you are actively using the keyboard or mouse\n"
                            "  • Which application is in focus\n"
                            "  • Browser URLs and tab titles\n"
                            "  • Periodic screenshots\n\n"
                            "Your administrator can review this data in the Horilla dashboard.\n"
                            "Keystrokes are only counted — never read or stored."
                        ),
                        "Horilla Agent",
                        win32con.MB_OK | win32con.MB_ICONINFORMATION,
                    )
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

        def _run(self):
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = "HorillaAgentTray"
            wc.lpfnWndProc = self._wndproc
            win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindow(
                wc.lpszClassName, "Horilla Agent",
                0, 0, 0, 0, 0, 0, 0, wc.hInstance, None,
            )
            self._notify(win32gui.NIM_ADD)
            win32gui.SetTimer(self.hwnd, 1, 30_000, None)
            win32gui.PumpMessages()
            self._notify(win32gui.NIM_DELETE)

# --------------------------------------------------------------------------- #
# Non-Windows stub (dev / CI)                                                  #
# --------------------------------------------------------------------------- #

else:
    class TrayIcon:
        def __init__(self, employee_name: str, collector, on_logout):
            self.employee_name = employee_name
            self.collector = collector
            self.on_logout = on_logout
            log.info("TrayIcon stub: running on non-Windows platform")

        def start(self):
            log.info("Tray stub started for %s", self.employee_name)
