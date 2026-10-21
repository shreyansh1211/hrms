"""
Main tracking loop.

Uses WindowWatcher (100 ms polling) for real-time window focus tracking.
Every time the focused window changes an activity event is queued with the
exact duration the previous window was in focus (in ms).

Every FLUSH_SECONDS the event queue is sent to the Uploader and a
"flush-current" event is also emitted for the window that is still open,
so long stays in the same app are recorded in ≤ MAX_SEGMENT_SECS chunks.

InputMonitor determines active/idle state; only active segments count toward
today_active_seconds.

Messaging apps (WhatsApp, Telegram, Slack, …) have their window title
suppressed for privacy — only the app name is recorded.
"""
import datetime
import logging
import random
import threading
import time

from tracker.app_tracker import WindowWatcher, should_hide_title
from tracker.browser_tracker import get_browser_url
from tracker.input_hook import InputMonitor
from tracker.screenshot import capture_jpeg

log = logging.getLogger("horilla_agent.collector")

FLUSH_SECONDS = 30       # how often to flush the event queue to the uploader
MAX_SEGMENT_SECS = 100   # split any single window event longer than this


class Collector(threading.Thread):
    daemon = True

    def __init__(self, session: dict, policy: dict, uploader):
        super().__init__(name="collector")
        self.session  = session
        self.policy   = policy
        self.uploader = uploader
        self.stop_event = threading.Event()

        self._monitor = InputMonitor(
            idle_threshold=policy.get("idle_threshold_seconds", 180)
        )
        self._watcher = WindowWatcher(self._on_window_event)

        self._next_screenshot = time.monotonic() + self._shot_interval()
        self._lock = threading.Lock()
        self._pending: list[dict] = []
        self._today_active_ms  = 0   # accumulated in ms, reported as seconds
        self._segments_collected = 0

    def _shot_interval(self) -> float:
        lo = self.policy.get("screenshot_interval_min", 300)
        hi = self.policy.get("screenshot_interval_max", 600)
        return random.uniform(lo, hi)

    @property
    def today_active(self) -> int:
        return self._today_active_ms // 1000

    @property
    def segments_collected(self) -> int:
        return self._segments_collected

    # ── window event callback (WindowWatcher thread) ─────────────────────────

    def _on_window_event(
        self,
        app: str,
        title: str,
        start_ts: float,
        end_ts: float,
        duration_ms: int,
    ):
        """
        Called when the focused window changes (or on a periodic flush).
        Builds one or more segments from the event and queues them.
        """
        active = self._monitor.is_active()

        # Privacy: messaging apps — no title
        clean_title = "" if should_hide_title(app) else title
        if not self.policy.get("capture_window_titles", True):
            clean_title = ""

        # URL only for active browser sessions
        url = ""
        if active and self.policy.get("capture_urls", True):
            url = get_browser_url(app)

        # Split long events into chunks ≤ MAX_SEGMENT_SECS
        duration_secs = end_ts - start_ts
        segments = []
        if duration_secs > MAX_SEGMENT_SECS:
            t = start_ts
            while t < end_ts:
                chunk_end = min(t + MAX_SEGMENT_SECS, end_ts)
                segments.append(_make_seg(app, clean_title, url, active, t, chunk_end))
                t = chunk_end
        else:
            segments.append(_make_seg(app, clean_title, url, active, start_ts, end_ts))

        with self._lock:
            self._pending.extend(segments)
            if active:
                self._today_active_ms += duration_ms

        # Log the event
        detail = url or clean_title or "—"
        if len(detail) > 60:
            detail = detail[:57] + "…"
        dur_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms/1000:.1f}s"
        if active:
            log.info("ACTIVE | %-22s | %-50s [%s]", app[:22], detail, dur_str)
        else:
            log.info("IDLE   | %-22s | %-50s [%s]", app[:22], detail, dur_str)

    # ── main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._monitor.start()
        self._watcher.start()
        log.info("STARTED | Tracking active for %s", self.session.get("employee_name"))

        while not self.stop_event.wait(FLUSH_SECONDS):
            # Emit an event for the currently focused window (still open)
            self._watcher.flush_current()

            # Drain the queue
            with self._lock:
                batch = self._pending[:]
                self._pending.clear()

            for seg in batch:
                self.uploader.push_segment(seg)
                self._segments_collected += 1

            # Log input counts for the flush period
            counts = self._monitor.consume_counts()
            win    = self._watcher.get_current()
            active = self._monitor.is_active()
            app_name = win.get("app", "") or "—"

            if counts["keys"] + counts["clicks"] + counts["moves"] > 0:
                log.info(
                    "ACTIVE | %-22s | [keys=%d clicks=%d moves=%d]",
                    app_name[:22], counts["keys"], counts["clicks"], counts["moves"],
                )
            elif not active:
                log.info("IDLE   | %-22s", app_name[:22])

            # Screenshot
            if active and time.monotonic() >= self._next_screenshot:
                self._next_screenshot = time.monotonic() + self._shot_interval()
                quality = self.policy.get("screenshot_jpeg_quality", 60)
                threading.Thread(
                    target=self._take_screenshot,
                    args=(win, quality),
                    daemon=True,
                ).start()

        self._watcher.stop()
        self._monitor.stop()
        log.info("STOPPED | Collector shut down")

    def _take_screenshot(self, win: dict, quality: int) -> None:
        try:
            b64 = capture_jpeg(quality=quality)
            if b64:
                self.uploader.push_screenshot(
                    b64,
                    app=win.get("app", ""),
                    title=win.get("title", ""),
                )
                log.info("SCREENSHOT | Captured and sent  (app: %s)", win.get("app", "—"))
        except Exception as exc:
            log.warning("SCREENSHOT | Failed: %s", exc)

    def stop(self) -> None:
        self.stop_event.set()


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _make_seg(
    app: str,
    title: str,
    url: str,
    active: bool,
    start_ts: float,
    end_ts: float,
) -> dict:
    return {
        "start":   _iso(start_ts),
        "end":     _iso(end_ts),
        "active":  active,
        "app":     app,
        "title":   title,
        "url":     url,
        "keys":    0,
        "clicks":  0,
        "moves":   0,
    }


def _iso(ts: float) -> str:
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")
