"""
Uploads tracked data to the Horilla server.

Batches segments every 60 s. App-usage and browser-tab daily rollups
are sent once per day (at next upload after midnight). Screenshots are
sent immediately after capture.

All uploads are retried on failure (exponential back-off, max 5 min).
Data is held in memory; on process restart unsent data is lost — the
30-second segment window is the acceptable data-loss window.
"""
import collections
import datetime
import logging
import threading
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("horilla_agent.uploader")

UPLOAD_INTERVAL = 60       # seconds between segment batch uploads
RETRY_DELAYS = [5, 15, 60, 300]


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
        self.stop_event = threading.Event()

    # ---- called from collector thread ------------------------------------ #

    def push_segment(self, seg: dict) -> None:
        with self._lock:
            self._segments.append(seg)
            # Accumulate app usage
            if seg.get("app") and seg.get("active"):
                dur = max(0, int(seg.get("end", 0)) - int(seg.get("start", 0)))
                self._app_seconds[seg["app"]] += dur
            # Accumulate browser tab usage
            url = seg.get("url", "")
            if url and seg.get("active"):
                dur = max(0, int(seg.get("end", 0)) - int(seg.get("start", 0)))
                if url not in self._tab_seconds:
                    self._tab_seconds[url] = {
                        "title": seg.get("title", ""),
                        "domain": _domain(url),
                        "seconds": 0,
                    }
                self._tab_seconds[url]["seconds"] += dur

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
            today = datetime.date.today()
            if self._last_flush_day != today:
                self._flush_daily(today)
                self._last_flush_day = today

    # ---- private --------------------------------------------------------- #

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.session['token']}"}

    def _base(self) -> str:
        return self.session["domain"].rstrip("/")

    def _post(self, path: str, payload: dict) -> bool:
        url = self._base() + path
        for delay in [0] + RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
                if r.ok:
                    return True
                if r.status_code in (401, 403):
                    log.warning("auth error posting %s — token may be expired", path)
                    return False
                log.warning("POST %s → %s", path, r.status_code)
            except requests.RequestException as exc:
                log.warning("POST %s failed: %s", path, exc)
        return False

    def _flush_segments(self) -> None:
        with self._lock:
            batch = self._segments[:]
            self._segments.clear()
        if not batch:
            return
        log.debug("uploading %d segments", len(batch))
        if not self._post("/activity/agent/segments/", {"segments": batch}):
            # Re-queue on failure (best-effort, avoid memory leak on long outage)
            with self._lock:
                self._segments = batch[:200] + self._segments

    def _flush_daily(self, day: datetime.date) -> None:
        with self._lock:
            apps = dict(self._app_seconds)
            tabs = dict(self._tab_seconds)
            self._app_seconds.clear()
            self._tab_seconds.clear()

        if apps:
            payload = {
                "date": day.isoformat(),
                "apps": [{"app": k, "seconds": v} for k, v in apps.items()],
            }
            self._post("/activity/agent/app-usage/", payload)

        if tabs:
            payload = {
                "date": day.isoformat(),
                "tabs": [
                    {"url": url, "title": v["title"], "seconds": v["seconds"]}
                    for url, v in tabs.items()
                ],
            }
            self._post("/activity/agent/browser-tabs/", payload)

    def _upload_screenshot(self, jpeg_b64: str, app: str, title: str) -> None:
        import datetime as dt
        payload = {
            "captured_at": dt.datetime.utcnow().isoformat() + "Z",
            "jpeg_b64": jpeg_b64,
            "active": True,
            "app": app,
            "title": title,
        }
        self._post("/activity/agent/screenshot/", payload)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""
