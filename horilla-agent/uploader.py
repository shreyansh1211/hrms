"""
Uploads tracked data to the Horilla server.

Segments
    Queued by the Collector (one per 60 s of active time).
    Sent every UPLOAD_INTERVAL seconds, OR immediately when
    trigger_flush() is called (e.g. on return from idle).

Daily totals (app usage + browser tabs)
    Accumulated by push_app_usage() from the WindowWatcher.
    Flushed every DAILY_FLUSH_INTERVAL seconds.

Screenshots
    Uploaded immediately in a fire-and-forget thread.
"""
import collections
import datetime
import logging
import threading
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("horilla_agent.uploader")

UPLOAD_INTERVAL      = 60   # segment flush interval (seconds)
DAILY_FLUSH_INTERVAL = 60   # app/browser daily totals flush (seconds)


class Uploader(threading.Thread):
    daemon = True

    def __init__(self, session: dict):
        super().__init__(name="uploader")
        self.session = session

        self._segments: list[dict] = []
        self._app_seconds: dict[str, int] = collections.defaultdict(int)
        self._tab_seconds: dict[str, dict] = {}   # url → {title, domain, seconds}

        self._lock = threading.Lock()
        self._flush_event = threading.Event()     # set to trigger immediate upload
        self._last_flush_day: datetime.date | None = None
        self._last_daily_flush: float = 0.0
        self.stop_event = threading.Event()

    # ── called from Collector / WindowWatcher threads ─────────────────────── #

    def push_segment(self, seg: dict) -> None:
        """Queue one activity segment for upload."""
        with self._lock:
            self._segments.append(seg)

    def push_app_usage(
        self,
        app: str,
        duration_secs: int,
        url: str = "",
        title: str = "",
    ) -> None:
        """Accumulate app + browser-tab time from WindowWatcher events."""
        if not app:
            return
        with self._lock:
            self._app_seconds[app] += duration_secs
            if url:
                if url not in self._tab_seconds:
                    self._tab_seconds[url] = {
                        "title":   title,
                        "domain":  _domain(url),
                        "seconds": 0,
                    }
                self._tab_seconds[url]["seconds"] += duration_secs
                if title:
                    self._tab_seconds[url]["title"] = title

    def push_screenshot(self, jpeg_b64: str, app: str, title: str) -> None:
        """Fire-and-forget screenshot upload."""
        threading.Thread(
            target=self._upload_screenshot,
            args=(jpeg_b64, app, title),
            daemon=True,
        ).start()

    def trigger_flush(self) -> None:
        """Signal the upload thread to flush immediately (called on idle→active)."""
        self._flush_event.set()

    # ── upload thread ─────────────────────────────────────────────────────── #

    def run(self) -> None:
        while not self.stop_event.is_set():
            # Wait up to UPLOAD_INTERVAL or until trigger_flush() wakes us
            triggered = self._flush_event.wait(timeout=UPLOAD_INTERVAL)
            self._flush_event.clear()

            if self.stop_event.is_set():
                break

            self._flush_segments()

            now   = time.time()
            today = datetime.date.today()
            if (
                (now - self._last_daily_flush) >= DAILY_FLUSH_INTERVAL
                or self._last_flush_day != today
            ):
                self._flush_daily(today)
                self._last_flush_day   = today
                self._last_daily_flush = now

    # ── private ───────────────────────────────────────────────────────────── #

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.session['token']}"}

    def _base(self) -> str:
        return self.session["domain"].rstrip("/")

    def _post(self, path: str, payload: dict) -> bool:
        url = self._base() + path
        try:
            r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
            if r.ok:
                return True
            if r.status_code in (401, 403):
                log.warning("UPLOAD | ✗ Auth error %s", r.status_code)
            else:
                log.warning("UPLOAD | ✗ Server %s for %s", r.status_code, path)
            return False
        except requests.RequestException as exc:
            log.warning("UPLOAD | ✗ Network: %s", exc)
            return False

    def _flush_segments(self) -> None:
        with self._lock:
            batch = self._segments[:]
            self._segments.clear()
        if not batch:
            return
        log.info("UPLOAD | Sending %d segment(s)…", len(batch))
        if self._post("/activity/agent/segments/", {"segments": batch}):
            log.info("UPLOAD | ✓ %d segment(s) saved", len(batch))
        else:
            log.warning("UPLOAD | ✗ Failed — re-queued for next cycle")
            with self._lock:
                self._segments = batch[:200] + self._segments

    def _flush_daily(self, day: datetime.date) -> None:
        with self._lock:
            apps = dict(self._app_seconds)
            tabs = dict(self._tab_seconds)
            self._app_seconds.clear()
            self._tab_seconds.clear()

        if apps:
            top = sorted(apps.items(), key=lambda x: -x[1])[:5]
            summary = "  ·  ".join(f"{n} {s // 60}m" for n, s in top)
            log.info("APP USE | %d app(s) — %s", len(apps), summary)
            payload = {
                "date": day.isoformat(),
                "apps": [{"app": k, "seconds": v} for k, v in apps.items()],
            }
            if self._post("/activity/agent/app-usage/", payload):
                log.info("APP USE | ✓ Sent")
            else:
                log.warning("APP USE | ✗ Failed")

        if tabs:
            top = sorted(tabs.items(), key=lambda x: -x[1]["seconds"])[:5]
            summary = "  ·  ".join(
                f"{v['domain'] or u} {v['seconds'] // 60}m" for u, v in top
            )
            log.info("BROWSER | %d tab(s) — %s", len(tabs), summary)
            payload = {
                "date": day.isoformat(),
                "tabs": [
                    {"url": u, "title": v["title"], "seconds": v["seconds"]}
                    for u, v in tabs.items()
                ],
            }
            if self._post("/activity/agent/browser-tabs/", payload):
                log.info("BROWSER | ✓ Sent")
            else:
                log.warning("BROWSER | ✗ Failed")

    def _upload_screenshot(self, jpeg_b64: str, app: str, title: str) -> None:
        import datetime as dt
        payload = {
            "captured_at": dt.datetime.utcnow().isoformat() + "Z",
            "jpeg_b64":    jpeg_b64,
            "active":      True,
            "app":         app,
            "title":       title,
        }
        if self._post("/activity/agent/screenshot/", payload):
            log.info("SCREENSHOT | ✓ Uploaded  (app: %s)", app or "—")
        else:
            log.warning("SCREENSHOT | ✗ Upload failed")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""
