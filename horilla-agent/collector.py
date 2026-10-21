"""
Main tracking loop — Horilla Agent.

Tracking concept
────────────────
• ACTIVE period  : user has keyboard / mouse input within idle_threshold secs.
                   One 60-second segment is sent to the server for every
                   60 seconds of active time (e.g. 8 minutes active → 8 segs).
• IDLE period    : no data is sent.  Idle time starts from the LAST real input
                   (not from when we detect it 3 min later).
• Return from idle: the very first moment is_active() flips back to True,
                   any queued segments are uploaded immediately.

Window / app tracking
─────────────────────
• WindowWatcher polls every 100 ms for focus changes.
• On every focus change it accumulates app-usage and browser-tab totals that
  are sent daily (not per-segment).
• Messaging apps (WhatsApp, Telegram, …) have their window title suppressed.
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

CHECK_INTERVAL   = 5     # seconds between idle/active checks
SEGMENT_INTERVAL = 60    # one segment per this many active seconds
MAX_SEG_SECS     = 100   # server-side cap — split anything longer


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
        self._today_active_seconds = 0
        self._segments_collected   = 0

    # ── public ───────────────────────────────────────────────────────────────

    @property
    def today_active(self) -> int:
        return self._today_active_seconds

    @property
    def segments_collected(self) -> int:
        return self._segments_collected

    def stop(self) -> None:
        self.stop_event.set()

    # ── WindowWatcher callback (background thread) ───────────────────────────

    def _on_window_event(
        self,
        app: str,
        title: str,
        start_ts: float,
        end_ts: float,
        duration_ms: int,
    ):
        """
        Called when the focused window changes.
        Used ONLY to accumulate daily app / browser totals — NOT for segments.
        """
        if not self._monitor.is_active():
            return   # don't accumulate idle time in usage totals

        url = ""
        if self.policy.get("capture_urls", True):
            url = get_browser_url(app)

        clean_title = "" if should_hide_title(app) else title

        dur_secs = max(1, duration_ms // 1000)
        self.uploader.push_app_usage(app, dur_secs, url, clean_title)

    # ── main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._monitor.start()
        self._watcher.start()
        log.info("STARTED | Tracking active for %s", self.session.get("employee_name"))

        _was_active    = True        # assume active at launch
        _idle_start: float | None = None
        _active_accum  = 0.0        # accumulated active seconds toward next segment
        _seg_wall_start = time.time()  # wall-clock start of current segment window

        while not self.stop_event.wait(CHECK_INTERVAL):
            now    = time.time()
            active = self._monitor.is_active()

            # ── Transition: ACTIVE → IDLE ────────────────────────────────────
            if _was_active and not active:
                # idle_start = wall-clock time of last real input
                idle_secs   = self._monitor.idle_seconds()
                _idle_start = now - idle_secs
                _active_accum = 0.0
                log.info(
                    "IDLE   | ↓ Went idle — last input at %s",
                    datetime.datetime.utcfromtimestamp(_idle_start).strftime("%H:%M:%S UTC"),
                )

            # ── Transition: IDLE → ACTIVE ────────────────────────────────────
            elif not _was_active and active:
                idle_end      = now
                idle_total    = idle_end - (_idle_start or idle_end)
                _idle_start   = None
                _active_accum = 0.0
                _seg_wall_start = now

                log.info(
                    "ACTIVE | ↑ Back from idle — idle for %s",
                    _fmt_dur(idle_total),
                )
                # Immediately flush any queued segments / daily totals
                self.uploader.trigger_flush()

            _was_active = active

            # ── Accumulate active time & emit segments ───────────────────────
            if active:
                _active_accum += CHECK_INTERVAL
                self._today_active_seconds += CHECK_INTERVAL

                if _active_accum >= SEGMENT_INTERVAL:
                    _active_accum -= SEGMENT_INTERVAL
                    seg_end   = now
                    seg_start = seg_end - SEGMENT_INTERVAL

                    win   = self._watcher.get_current()
                    app   = win.get("app", "")
                    title = win.get("title", "")

                    clean_title = "" if should_hide_title(app) else title
                    if not self.policy.get("capture_window_titles", True):
                        clean_title = ""

                    url = ""
                    if self.policy.get("capture_urls", True):
                        url = get_browser_url(app)

                    counts = self._monitor.consume_counts()
                    seg = _make_seg(app, clean_title, url, True, seg_start, seg_end,
                                    counts["keys"], counts["clicks"], counts["moves"])
                    self.uploader.push_segment(seg)
                    self._segments_collected += 1
                    _seg_wall_start = now

                    detail = url or clean_title or "—"
                    if len(detail) > 60:
                        detail = detail[:57] + "…"
                    log.info(
                        "ACTIVE | %-22s | %-50s [keys=%d clicks=%d]",
                        (app or "—")[:22], detail, counts["keys"], counts["clicks"],
                    )

            # ── Screenshot ───────────────────────────────────────────────────
            if active and time.monotonic() >= self._next_screenshot:
                self._next_screenshot = time.monotonic() + self._shot_interval()
                quality = self.policy.get("screenshot_jpeg_quality", 60)
                win = self._watcher.get_current()
                threading.Thread(
                    target=self._take_screenshot,
                    args=(win, quality),
                    daemon=True,
                ).start()

        self._watcher.stop()
        self._monitor.stop()
        log.info("STOPPED | Collector shut down")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _shot_interval(self) -> float:
        lo = self.policy.get("screenshot_interval_min", 300)
        hi = self.policy.get("screenshot_interval_max", 600)
        return random.uniform(lo, hi)

    def _take_screenshot(self, win: dict, quality: int) -> None:
        try:
            b64 = capture_jpeg(quality=quality)
            if b64:
                self.uploader.push_screenshot(
                    b64,
                    app=win.get("app", ""),
                    title=win.get("title", ""),
                )
                log.info("SCREENSHOT | Captured  (app: %s)", win.get("app", "—"))
        except Exception as exc:
            log.warning("SCREENSHOT | Failed: %s", exc)


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
    keys: int = 0,
    clicks: int = 0,
    moves: int = 0,
) -> dict:
    return {
        "start":  _iso(start_ts),
        "end":    _iso(end_ts),
        "active": active,
        "app":    app,
        "title":  title,
        "url":    url,
        "keys":   keys,
        "clicks": clicks,
        "moves":  moves,
    }


def _iso(ts: float) -> str:
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_dur(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m {secs % 60:02d}s"
