"""
Main tracking loop — Infisetu Agent.

Tracking concept
────────────────
• ACTIVE period  : user has keyboard / mouse input within idle_threshold secs.
                   Every 300 seconds (5 min) of active time, all buffered
                   window events are packaged into segments and sent to the
                   server.
• IDLE period    : no data is sent.  Idle time starts from the LAST real input
                   (not from when we detect it ~3 min later).
• Return from idle: all buffered window events are sent immediately as active
                   segments, plus one active=False segment covering the full
                   idle period.

Window / app tracking
─────────────────────
• WindowWatcher polls every 100 ms for focus changes.
• On every focus change _on_window_event fires — but is a no-op while idle,
  so no phantom events accumulate.
• Daily app-usage and browser-tab totals are accumulated separately and sent
  via a different endpoint.
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

log = logging.getLogger("infisetu_agent.collector")

CHECK_INTERVAL   = 5     # seconds between idle/active checks
SEGMENT_INTERVAL = 300   # flush buffer every N active seconds (5 min)
MAX_SEG_SECS     = 110   # split active segments longer than this (server cap is 120)


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

        self._next_screenshot      = time.monotonic() + self._shot_interval()
        self._today_active_seconds = 0
        self._segments_collected   = 0

        # Buffer: window events waiting to be sent (only filled while active)
        self._buffer: list[dict] = []
        self._buf_lock = threading.Lock()

        # Idle tracking
        self._is_idle   = False           # gate for _on_window_event
        self._idle_start: float | None = None  # epoch of last real input

    # ── public ───────────────────────────────────────────────────────────────

    @property
    def today_active(self) -> int:
        return self._today_active_seconds

    @property
    def segments_collected(self) -> int:
        return self._segments_collected

    def stop(self) -> None:
        self.stop_event.set()

    # ── WindowWatcher callback (100 ms thread) ───────────────────────────────

    def _on_window_event(
        self,
        app: str,
        title: str,
        start_ts: float,
        end_ts: float,
        duration_ms: int,
    ):
        """
        Called when the focused window changes (or flush_current() is called).

        Ignored entirely during idle periods — this is the critical gate that
        prevents phantom window events from being buffered while the user is
        away from the keyboard.
        """
        if self._is_idle:
            return

        url = ""
        if self.policy.get("capture_urls", True):
            url = get_browser_url(app)

        clean_title = "" if should_hide_title(app) else title
        if not self.policy.get("capture_window_titles", True):
            clean_title = ""

        # Accumulate daily app / browser totals (separate endpoint)
        dur_secs = max(1, duration_ms // 1000)
        self.uploader.push_app_usage(app, dur_secs, url, clean_title)

        # Buffer the window span for the next periodic / idle-return flush
        with self._buf_lock:
            self._buffer.append({
                "app":   app,
                "title": clean_title,
                "url":   url,
                "start": start_ts,
                "end":   end_ts,
            })

    # ── main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._monitor.start()
        self._watcher.start()
        log.info("STARTED | Tracking active for %s", self.session.get("employee_name"))

        _was_active   = True   # assume active at launch
        _active_accum = 0.0    # accumulated active seconds toward next flush

        while not self.stop_event.wait(CHECK_INTERVAL):
            now         = time.time()
            idle_secs   = self._monitor.idle_seconds()
            idle_thresh = self.policy.get("idle_threshold_seconds", 180)
            active      = idle_secs < idle_thresh

            # ── Transition: ACTIVE → IDLE ────────────────────────────────────
            if _was_active and not active:
                # Idle started at the time of the last real input, NOT now
                idle_start       = now - idle_secs
                self._idle_start = idle_start
                _active_accum    = 0.0

                # Close the current window span precisely at last-input time
                # so we don't count the "detected" idle gap as active time
                self._watcher.flush_current(end_ts=idle_start)
                self._is_idle = True

                log.info(
                    "IDLE   | ↓ Went idle — last input at %s",
                    datetime.datetime.utcfromtimestamp(idle_start).strftime(
                        "%H:%M:%S UTC"
                    ),
                )

            # ── Transition: IDLE → ACTIVE ────────────────────────────────────
            elif not _was_active and active:
                idle_end   = now
                idle_total = idle_end - (self._idle_start or idle_end)

                # Re-enable buffering before reset_start so the first window
                # event after wake is captured correctly
                self._is_idle = False
                self._watcher.reset_start()   # discard window time spent idle
                _active_accum = 0.0

                log.info(
                    "ACTIVE | ↑ Back from idle — idle for %s",
                    _fmt_dur(idle_total),
                )

                # Package everything: buffered active windows + idle segment
                counts = self._monitor.consume_counts()
                segs = self._drain_buffer(counts)
                if self._idle_start is not None:
                    segs += _idle_segs(self._idle_start, idle_end)
                self._idle_start = None

                for seg in segs:
                    self.uploader.push_segment(seg)
                    self._segments_collected += 1

                if segs:
                    log.info(
                        "FLUSH  | Idle return — %d segment(s) queued", len(segs)
                    )

                # Wake the uploader immediately (don't wait up to 60 s)
                self.uploader.trigger_flush()

            _was_active = active

            # ── Accumulate active time & periodic 5-min flush ────────────────
            if active:
                _active_accum          += CHECK_INTERVAL
                self._today_active_seconds += CHECK_INTERVAL

                if _active_accum >= SEGMENT_INTERVAL:
                    _active_accum -= SEGMENT_INTERVAL

                    # Emit the current window so it lands in the buffer
                    self._watcher.flush_current()

                    counts = self._monitor.consume_counts()
                    segs   = self._drain_buffer(counts)
                    for seg in segs:
                        self.uploader.push_segment(seg)
                        self._segments_collected += 1

                    if segs:
                        top = segs[0]
                        detail = top.get("url") or top.get("title") or "—"
                        if len(detail) > 60:
                            detail = detail[:57] + "…"
                        log.info(
                            "FLUSH  | 5-min cycle (%d seg) — %s",
                            len(segs),
                            detail,
                        )

                    self.uploader.trigger_flush()

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

    def _drain_buffer(self, counts: dict) -> list[dict]:
        """
        Pop all events from the buffer, convert to segments (splitting long
        ones at MAX_SEG_SECS), and distribute input counts proportionally.
        """
        with self._buf_lock:
            buf = self._buffer[:]
            self._buffer.clear()

        if not buf:
            return []

        total_keys   = counts.get("keys",   0)
        total_clicks = counts.get("clicks", 0)
        total_moves  = counts.get("moves",  0)
        total_dur    = sum(max(0.0, e["end"] - e["start"]) for e in buf) or 1.0

        segs = []
        for event in buf:
            dur   = max(0.0, event["end"] - event["start"])
            ratio = dur / total_dur
            segs += _split_event(
                app    = event["app"],
                title  = event["title"],
                url    = event["url"],
                start  = event["start"],
                end    = event["end"],
                keys   = int(total_keys   * ratio),
                clicks = int(total_clicks * ratio),
                moves  = int(total_moves  * ratio),
            )

        return segs

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

def _split_event(
    app: str,
    title: str,
    url: str,
    start: float,
    end: float,
    keys: int = 0,
    clicks: int = 0,
    moves: int = 0,
) -> list[dict]:
    """
    Split an active window event into ≤MAX_SEG_SECS chunks.
    Input counts are distributed proportionally across chunks.
    """
    dur = end - start
    if dur <= 0:
        return []

    chunks = []
    t = start
    while t < end:
        chunk_end = min(t + MAX_SEG_SECS, end)
        chunk_dur = chunk_end - t
        ratio     = chunk_dur / dur
        chunks.append(_make_seg(
            app, title, url, True, t, chunk_end,
            int(keys * ratio), int(clicks * ratio), int(moves * ratio),
        ))
        t = chunk_end

    return chunks


def _idle_segs(idle_start: float, idle_end: float) -> list[dict]:
    """
    Create active=False segment(s) covering the idle period.
    Chunks at 86400 s to satisfy server-side duration validation.
    """
    MAX_IDLE_SEG = 86400
    segs = []
    t = idle_start
    while t < idle_end:
        chunk_end = min(t + MAX_IDLE_SEG, idle_end)
        segs.append(_make_seg("", "", "", False, t, chunk_end))
        t = chunk_end
    return segs


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
