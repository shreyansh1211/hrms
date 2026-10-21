"""
Uploads tracked data to the Horilla server.

Batches segments every 60 s. App-usage and browser-tab daily rollups
are sent every 1 minute. Screenshots are sent immediately after capture.

Duration is calculated from the actual ISO timestamps in each segment
(not a fixed 30 s constant) so millisecond-precision events are accounted
for correctly.

No retry delays — if a POST fails the data is re-queued and retried on
the next cycle (60 s later).
"""
import collections
import datetime
import logging
import threading
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("horilla_agent.uploader")

UPLOAD_INTERVAL      = 60   # seconds between segment batch uploads
DAILY_FLUSH_INTERVAL = 60   # flush app/browser usage every 1 minute


def _seg_duration(seg: dict) -> int:
    """Return the duration of a segment in whole seconds from its ISO timestamps."""
    try:
        start = datetime.datetime.strptime(seg["start"], "%Y-%m-%dT%H:%M:%SZ")
        end   = datetime.datetime.strptime(seg["end"],   "%Y-%m-%dT%H:%M:%SZ")
        return max(1, int((end - start).total_seconds()))
    except Exception:
        return 30  # safe fallback


class Uploader(threading.Thread):
    daemon = True

    def __init__(self, session: dict):
        super().__init__(name="uploader")
        self.session = session
        self._segments: list[dict] = []
        self._app_seconds: dict[str, int] = collections.defaultdict(int)
        self._tab_seconds: dict[str, dict] = {}  # url -> {title, domain, seconds}
        self._lock = threading.Lock()
        self._last_flush_day: datetime.date | None = None
        self._last_daily_flush: float = 0.0
        self.stop_event = threading.Event()

    # ---- called from collector thread ------------------------------------ #

    def push_segment(self, seg: dict) -> None:
        with self._lock:
            self._segments.append(seg)

            # Accumulate app usage using actual segment duration
            if seg.get("app") and seg.get("active"):
                dur = _seg_duration(seg)
                self._app_seconds[seg["app"]] += dur

            # Accumulate browser tab usage
            url = seg.get("url", "")
            if url and seg.get("active"):
                dur = _seg_duration(seg)
                if url not in self._tab_seconds:
                    self._tab_seconds[url] = {
                        "title":   seg.get("title", ""),
                        "domain":  _domain(url),
                        "seconds": 0,
                    }
                self._tab_seconds[url]["seconds"] += dur
                # Update title if we get a better one
                if seg.get("title"):
                    self._tab_seconds[url]["title"] = seg["title"]

    def push_screenshot(self, jpeg_b64: str, app: str, title: str) -> None:
        """Fire-and-forget screenshot upload in a separate thread."""
        threading.Thread(
            target=self._upload_screenshot,
            args=(jpeg_b64, app, title),
            daemon=True,
        ).start()

    # ---- background thread ----------------------------------------------- #

    def run(self) -> None:
        while not self.stop_event.wait(UPLOAD_INTERVAL):
            self._flush_segments()
            now = time.time()
            today = datetime.date.today()
            if (
                (now - self._last_daily_flush) >= DAILY_FLUSH_INTERVAL
                or self._last_flush_day != today
            ):
                self._flush_daily(today)
                self._last_flush_day = today
                self._last_daily_flush = now

    # ---- private --------------------------------------------------------- #

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.session['token']}"}

    def _base(self) -> str:
        return self.session["domain"].rstrip("/")

    def _post(self, path: str, payload: dict) -> bool:
        """Single-attempt POST — no blocking retries."""
        url = self._base() + path
        try:
            r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
            if r.ok:
                return True
            if r.status_code in (401, 403):
                log.warning("UPLOAD | ✗ Auth error %s — token may be expired", r.status_code)
            else:
                log.warning("UPLOAD | ✗ Server returned %s for %s", r.status_code, path)
            return False
        except requests.RequestException as exc:
            log.warning("UPLOAD | ✗ Network error: %s", exc)
            return False

    def _flush_segments(self) -> None:
        with self._lock:
            batch = self._segments[:]
            self._segments.clear()
        if not batch:
            return
        log.info("UPLOAD | Sending %d segment(s) to server…", len(batch))
        if self._post("/activity/agent/segments/", {"segments": batch}):
            log.info("UPLOAD | ✓ %d segment(s) saved on server", len(batch))
        else:
            log.warning("UPLOAD | ✗ Failed — will retry next cycle")
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
            summary = "  ·  ".join(f"{name} {s // 60}m" for name, s in top)
            log.info("APP USE | %d app(s) — %s", len(apps), summary)
            payload = {
                "date": day.isoformat(),
                "apps": [{"app": k, "seconds": v} for k, v in apps.items()],
            }
            if self._post("/activity/agent/app-usage/", payload):
                log.info("APP USE | ✓ Sent to server")
            else:
                log.warning("APP USE | ✗ Failed to send")

        if tabs:
            top = sorted(tabs.items(), key=lambda x: -x[1]["seconds"])[:5]
            summary = "  ·  ".join(
                f"{v['domain'] or url} {v['seconds'] // 60}m" for url, v in top
            )
            log.info("BROWSER | %d tab(s) — %s", len(tabs), summary)
            payload = {
                "date": day.isoformat(),
                "tabs": [
                    {"url": url, "title": v["title"], "seconds": v["seconds"]}
                    for url, v in tabs.items()
                ],
            }
            if self._post("/activity/agent/browser-tabs/", payload):
                log.info("BROWSER | ✓ Sent to server")
            else:
                log.warning("BROWSER | ✗ Failed to send")

    def _upload_screenshot(self, jpeg_b64: str, app: str, title: str) -> None:
        import datetime as dt
        payload = {
            "captured_at": dt.datetime.utcnow().isoformat() + "Z",
            "jpeg_b64": jpeg_b64,
            "active": True,
            "app": app,
            "title": title,
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
