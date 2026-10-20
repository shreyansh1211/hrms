"""
Read-only client for the Infi Time Manager totals API (/api/v1/active-time).

Configuration (settings / .env):
    ACTIVITY_TRACKER_URL=http://127.0.0.1:8001       (the tracker server, same VPS)
    ACTIVITY_TRACKER_API_KEY=itm_...                  (Console -> Settings -> Create API key)
    ACTIVITY_TRACKER_CONSOLE_URL=https://time.example.com   (admin console, for links)
"""

import requests
from django.conf import settings

TIMEOUT = 8


class TrackerError(Exception):
    pass


def configured():
    return bool(
        getattr(settings, "ACTIVITY_TRACKER_URL", "")
        and getattr(settings, "ACTIVITY_TRACKER_API_KEY", "")
    )


def http_get(url, params, headers):
    return requests.get(url, params=params, headers=headers, timeout=TIMEOUT)


def fetch_all(start, end):
    """Everyone's daily totals for start..end (dates). Returns the 'employees' list."""
    if not configured():
        raise TrackerError("The activity tracker is not configured.")
    url = settings.ACTIVITY_TRACKER_URL.rstrip("/") + "/api/v1/active-time"
    try:
        response = http_get(
            url,
            {"start": start.isoformat(), "end": end.isoformat()},
            {"Authorization": f"Bearer {settings.ACTIVITY_TRACKER_API_KEY}"},
        )
    except requests.RequestException as exc:
        raise TrackerError(f"Could not reach the activity tracker: {exc}") from exc
    if response.status_code != 200:
        raise TrackerError(f"Activity tracker answered {response.status_code}.")
    try:
        return response.json().get("employees", [])
    except ValueError as exc:
        raise TrackerError("The activity tracker sent an unreadable reply.") from exc
