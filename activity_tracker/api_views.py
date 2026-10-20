"""REST API consumed by the Horilla desktop agent.

All endpoints are under /activity/agent/  and use token-based auth
(Authorization: Bearer <token>) except the login endpoint itself.

Endpoints:
    POST /activity/agent/login/          - trade Horilla creds for a 30-day agent token
    POST /activity/agent/segments/       - upload activity segments
    POST /activity/agent/screenshot/     - upload a single screenshot
    POST /activity/agent/app-usage/      - upload aggregated app usage for a day
    POST /activity/agent/browser-tabs/   - upload aggregated browser-tab usage for a day
    GET  /activity/agent/policy/         - fetch tracking policy (idle threshold, screenshot interval)
"""

import base64
import io
import json
import logging
from datetime import date, timedelta
from urllib.parse import urlparse

from django.contrib.auth import authenticate
from django.core.files.base import ContentFile
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse

from activity_tracker.models import (
    ActivitySegment,
    AgentToken,
    AppUsageLog,
    BrowserTabLog,
    EmployeeScreenshot,
)

log = logging.getLogger("activity_tracker.api")

# --- helpers -----------------------------------------------------------------


def _json_body(request):
    try:
        return json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None


def _auth_token(request):
    """Resolve the bearer token from the request; return AgentToken or None."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Bearer "):
        return None
    raw = header[7:].strip()
    try:
        tok = AgentToken.objects.select_related("employee").get(token=raw)
    except AgentToken.DoesNotExist:
        return None
    if not tok.is_valid():
        return None
    tok.touch()
    return tok


def _err(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def _ok(data=None, status=200):
    return JsonResponse(data or {"ok": True}, status=status)


# --- views -------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def agent_login(request):
    """
    Authenticate with Horilla credentials and receive a 30-day agent token.

    Request body (JSON):
        {
            "email": "employee@example.com",
            "password": "secret",
            "device_name": "DESKTOP-ABC123"   (optional)
        }

    Response:
        {
            "token": "...",
            "expires_at": "2026-11-19T12:00:00Z",
            "employee_id": 7,
            "employee_name": "Asha Rao"
        }
    """
    body = _json_body(request)
    if not body:
        return _err("Invalid JSON body.")

    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    device_name = (body.get("device_name") or "")[:200]

    if not email or not password:
        return _err("email and password are required.")

    # Try authenticating by username=email (Horilla uses email as username)
    user = authenticate(request, username=email, password=password)
    if user is None:
        # Some installs store email separately; try via email field
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            u = User.objects.get(email=email)
            user = authenticate(request, username=u.username, password=password)
        except User.DoesNotExist:
            pass

    if user is None or not user.is_active:
        return _err("Invalid credentials.", status=401)

    employee = getattr(user, "employee_get", None)
    if employee is None:
        return _err("No employee record linked to this account.", status=403)

    # Revoke old tokens for this device name to keep things tidy
    if device_name:
        AgentToken.objects.filter(
            employee=employee, device_name=device_name, is_active=True
        ).update(is_active=False)

    tok = AgentToken.create_for(employee, device_name=device_name)

    return _ok(
        {
            "token": tok.token,
            "expires_at": tok.expires_at.isoformat(),
            "employee_id": employee.pk,
            "employee_name": employee.get_full_name(),
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["POST"])
def agent_segments(request):
    """
    Upload a batch of activity segments.

    Request body (JSON):
        {
            "segments": [
                {
                    "start": "2026-10-20T09:00:00Z",
                    "end":   "2026-10-20T09:02:00Z",
                    "active": true,
                    "app": "Chrome",
                    "title": "Google — Search",
                    "url": "https://google.com",
                    "keys": 42,
                    "clicks": 5,
                    "moves": 120
                },
                ...
            ]
        }
    """
    tok = _auth_token(request)
    if not tok:
        return _err("Unauthorized.", status=401)

    body = _json_body(request)
    if not body or "segments" not in body:
        return _err("Expected {'segments': [...]}.")

    now = timezone.now()
    saved = 0
    for s in body["segments"][:500]:  # cap per request
        try:
            start = _parse_dt(s["start"])
            end = _parse_dt(s["end"])
        except (KeyError, ValueError, TypeError):
            continue
        if start is None or end is None:
            continue
        if end <= start or (end - start).total_seconds() > 120:
            continue
        if end > now + timedelta(seconds=30):
            continue  # future
        ActivitySegment.objects.create(
            employee=tok.employee,
            start=start,
            end=end,
            active=bool(s.get("active", False)),
            app_name=str(s.get("app", ""))[:200],
            window_title=str(s.get("title", ""))[:500],
            url=str(s.get("url", ""))[:1000],
            keys=max(0, int(s.get("keys", 0))),
            clicks=max(0, int(s.get("clicks", 0))),
            moves=max(0, int(s.get("moves", 0))),
        )
        saved += 1

    # Rebuild daily totals for affected dates
    _rebuild_daily_totals(tok.employee)

    return _ok({"saved": saved})


@csrf_exempt
@require_http_methods(["POST"])
def agent_screenshot(request):
    """
    Upload a single JPEG screenshot (base64-encoded).

    Request body (JSON):
        {
            "captured_at": "2026-10-20T09:05:00Z",
            "jpeg_b64": "<base64 string>",
            "active": true,
            "app": "Chrome",
            "title": "Dashboard"
        }
    """
    tok = _auth_token(request)
    if not tok:
        return _err("Unauthorized.", status=401)

    body = _json_body(request)
    if not body or "jpeg_b64" not in body:
        return _err("Expected jpeg_b64.")

    captured_at = _parse_dt(body.get("captured_at")) or timezone.now()

    try:
        jpeg_bytes = base64.b64decode(body["jpeg_b64"])
    except Exception:
        return _err("Invalid base64 for jpeg_b64.")

    if len(jpeg_bytes) > 5 * 1024 * 1024:  # 5 MB cap
        return _err("Screenshot too large (max 5 MB).")

    filename = f"{tok.employee.pk}_{captured_at.strftime('%Y%m%d_%H%M%S')}.jpg"
    shot = EmployeeScreenshot(
        employee=tok.employee,
        captured_at=captured_at,
        active_at_capture=bool(body.get("active", True)),
        app_name=str(body.get("app", ""))[:200],
        window_title=str(body.get("title", ""))[:500],
    )
    shot.image.save(filename, ContentFile(jpeg_bytes), save=True)

    return _ok({"id": shot.pk}, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def agent_app_usage(request):
    """
    Upload aggregated app-usage totals for one day.

    Request body (JSON):
        {
            "date": "2026-10-20",
            "apps": [
                {"app": "Chrome",   "seconds": 3600},
                {"app": "VS Code",  "seconds": 7200}
            ]
        }
    """
    tok = _auth_token(request)
    if not tok:
        return _err("Unauthorized.", status=401)

    body = _json_body(request)
    if not body:
        return _err("Invalid JSON.")

    try:
        day = date.fromisoformat(body["date"])
    except (KeyError, ValueError):
        return _err("date is required (YYYY-MM-DD).")

    saved = 0
    for item in (body.get("apps") or [])[:200]:
        app_name = str(item.get("app", ""))[:200].strip()
        seconds = max(0, int(item.get("seconds", 0)))
        if not app_name:
            continue
        obj, created = AppUsageLog.objects.get_or_create(
            employee=tok.employee, date=day, app_name=app_name,
            defaults={"seconds": seconds},
        )
        if not created:
            obj.seconds = seconds
            obj.save(update_fields=["seconds"])
        saved += 1

    return _ok({"saved": saved})


@csrf_exempt
@require_http_methods(["POST"])
def agent_browser_tabs(request):
    """
    Upload aggregated browser-tab usage totals for one day.

    Request body (JSON):
        {
            "date": "2026-10-20",
            "tabs": [
                {"url": "https://github.com", "title": "GitHub", "seconds": 1200},
                {"url": "https://google.com", "title": "Google", "seconds": 300}
            ]
        }
    """
    tok = _auth_token(request)
    if not tok:
        return _err("Unauthorized.", status=401)

    body = _json_body(request)
    if not body:
        return _err("Invalid JSON.")

    try:
        day = date.fromisoformat(body["date"])
    except (KeyError, ValueError):
        return _err("date is required (YYYY-MM-DD).")

    saved = 0
    for item in (body.get("tabs") or [])[:500]:
        url = str(item.get("url", ""))[:1000].strip()
        title = str(item.get("title", ""))[:500]
        seconds = max(0, int(item.get("seconds", 0)))
        if not url:
            continue
        domain = _domain(url)
        # Upsert by (employee, date, url) — keep latest seconds
        obj, created = BrowserTabLog.objects.get_or_create(
            employee=tok.employee, date=day, url=url,
            defaults={"title": title, "domain": domain, "seconds": seconds},
        )
        if not created:
            obj.seconds = seconds
            obj.title = title
            obj.domain = domain
            obj.save(update_fields=["seconds", "title", "domain"])
        saved += 1

    return _ok({"saved": saved})


@require_http_methods(["GET"])
def agent_policy(request):
    """Return the current tracking policy so the agent can adjust its behaviour."""
    tok = _auth_token(request)
    if not tok:
        return _err("Unauthorized.", status=401)
    return _ok(
        {
            "idle_threshold_seconds": 180,       # 3 min idle → stop timer
            "screenshot_interval_min": 300,      # 5 min min
            "screenshot_interval_max": 600,      # 10 min max
            "screenshot_jpeg_quality": 60,
            "capture_urls": True,
            "capture_window_titles": True,
        }
    )


# --- helpers -----------------------------------------------------------------


def _parse_dt(value):
    if not value:
        return None
    from django.utils.dateparse import parse_datetime
    dt = parse_datetime(str(value))
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""


def _rebuild_daily_totals(employee):
    """Recompute ActiveTimeDay from ActivitySegment rows for the last 2 days."""
    from activity_tracker.models import ActiveTimeDay

    for delta in (0, 1):
        day = (timezone.now() - timedelta(days=delta)).date()
        segments = ActivitySegment.objects.filter(
            employee=employee,
            start__date=day,
        )
        active_secs = sum(
            s.duration_seconds() for s in segments if s.active
        )
        tracked_secs = sum(s.duration_seconds() for s in segments)
        first_seen = segments.order_by("start").values_list("start", flat=True).first()
        last_seen = segments.order_by("-end").values_list("end", flat=True).first()

        if tracked_secs == 0 and delta > 0:
            continue

        ActiveTimeDay.objects.update_or_create(
            employee_id=employee,
            date=day,
            defaults={
                "active_seconds": active_secs,
                "tracked_seconds": tracked_secs,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "agent_status": "online" if delta == 0 else "",
            },
        )
