"""
Main tracking loop.

Runs in a background thread after login. Every SEGMENT_SECONDS it emits
one activity segment (active or idle), captures app/URL, and triggers
screenshots on the configured interval.
"""
import datetime
import logging
import random
import threading
import time

from tracker.app_tracker import get_active_window
from tracker.browser_tracker import get_browser_url
from tracker.input_hook import InputMonitor
from tracker.screenshot import capture_jpeg

log = logging.getLogger("horilla_agent.collector")

SEGMENT_SECONDS = 30  # emit a segment every 30 s


class Collector(threading.Thread):
    daemon = True

    def __init__(self, session: dict, policy: dict, uploader):
        super().__init__(name="collector")
        self.session = session
        self.policy = policy
        self.uploader = uploader
        self.stop_event = threading.Event()
        self._monitor = InputMonitor(
            idle_threshold=policy.get("idle_threshold_seconds", 180)
        )
        self._next_screenshot = time.monotonic() + self._shot_interval()
        self._today_active_seconds = 0

    def _shot_interval(self) -> float:
        lo = self.policy.get("screenshot_interval_min", 300)
        hi = self.policy.get("screenshot_interval_max", 600)
        return random.uniform(lo, hi)

    @property
    def today_active(self) -> int:
        return self._today_active_seconds

    def run(self) -> None:
        self._monitor.start()
        log.info("collector started for %s", self.session.get("employee_name"))

        while not self.stop_event.wait(SEGMENT_SECONDS):
            now = time.time()
            start = now - SEGMENT_SECONDS
            active = self._monitor.is_active()
            counts = self._monitor.consume_counts()

            win = get_active_window()
            url = ""
            if active and self.policy.get("capture_urls", True):
                url = get_browser_url(win.get("app", ""))

            title = win.get("title", "") if self.policy.get("capture_window_titles", True) else ""

            seg = {
                "start": _iso(start),
                "end": _iso(now),
                "active": active,
                "app": win.get("app", ""),
                "title": title,
                "url": url,
                "keys": counts["keys"],
                "clicks": counts["clicks"],
                "moves": counts["moves"],
            }
            self.uploader.push_segment(seg)

            if active:
                self._today_active_seconds += SEGMENT_SECONDS

            # Screenshot
            if active and time.monotonic() >= self._next_screenshot:
                self._next_screenshot = time.monotonic() + self._shot_interval()
                quality = self.policy.get("screenshot_jpeg_quality", 60)
                threading.Thread(
                    target=self._take_screenshot,
                    args=(win, quality),
                    daemon=True,
                ).start()

        self._monitor.stop()
        log.info("collector stopped")

    def _take_screenshot(self, win: dict, quality: int) -> None:
        try:
            b64 = capture_jpeg(quality=quality)
            if b64:
                self.uploader.push_screenshot(
                    b64,
                    app=win.get("app", ""),
                    title=win.get("title", ""),
                )
        except Exception as exc:
            log.warning("screenshot failed: %s", exc)

    def stop(self) -> None:
        self.stop_event.set()


def _iso(ts: float) -> str:
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")
