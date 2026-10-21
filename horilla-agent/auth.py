"""
Horilla agent authentication.

Authenticates the employee with their Horilla credentials (domain + email + password)
and stores a 30-day token so the agent stays logged in across reboots.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
# Token storage                                                                #
# --------------------------------------------------------------------------- #

def _token_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    d = base / "InfisetuAgent"
    d.mkdir(parents=True, exist_ok=True)
    return d / "session.json"


def save_session(domain: str, token: str, expires_at: str,
                 employee_id: int, employee_name: str) -> None:
    _token_path().write_text(
        json.dumps({
            "domain": domain.rstrip("/"),
            "token": token,
            "expires_at": expires_at,
            "employee_id": employee_id,
            "employee_name": employee_name,
        }),
        encoding="utf-8",
    )


def load_session() -> dict | None:
    p = _token_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Check expiry
    try:
        exp = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        if exp <= datetime.now(timezone.utc):
            p.unlink(missing_ok=True)
            return None
    except Exception:
        return None
    return data


def clear_session() -> None:
    _token_path().unlink(missing_ok=True)


def is_logged_in() -> bool:
    return load_session() is not None


# --------------------------------------------------------------------------- #
# Login                                                                        #
# --------------------------------------------------------------------------- #

class AuthError(Exception):
    pass


def login(domain: str, email: str, password: str,
          device_name: str = "") -> dict:
    """
    POST /activity/agent/login/ on the Horilla server.
    Returns the session dict on success; raises AuthError on failure.
    """
    url = domain.rstrip("/") + "/activity/agent/login/"
    try:
        resp = requests.post(
            url,
            json={"email": email, "password": password, "device_name": device_name},
            timeout=15,
        )
    except requests.ConnectionError:
        raise AuthError(f"Cannot reach {domain}. Check the domain and your internet connection.")
    except requests.Timeout:
        raise AuthError("Connection timed out. Check the domain.")

    if resp.status_code == 401:
        raise AuthError("Invalid email or password.")
    if resp.status_code == 403:
        raise AuthError("Your account has no employee record. Contact your administrator.")
    if not resp.ok:
        raise AuthError(f"Server error ({resp.status_code}). Contact your administrator.")

    data = resp.json()
    save_session(
        domain=domain,
        token=data["token"],
        expires_at=data["expires_at"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
    )
    return load_session()


def fetch_policy(session: dict) -> dict:
    """Fetch tracking policy from Horilla. Returns defaults on error."""
    defaults = {
        "idle_threshold_seconds": 180,
        "screenshot_interval_min": 300,
        "screenshot_interval_max": 600,
        "screenshot_jpeg_quality": 60,
        "capture_urls": True,
        "capture_window_titles": True,
    }
    try:
        url = session["domain"] + "/activity/agent/policy/"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {session['token']}"},
            timeout=10,
        )
        if resp.ok:
            return {**defaults, **resp.json()}
    except Exception:
        pass
    return defaults
