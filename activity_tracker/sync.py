"""Copy the tracker's daily totals into ActiveTimeDay and match them to employees."""

import datetime
import logging

from django.db.models import Q
from django.utils import timezone

from activity_tracker import client
from activity_tracker.models import ActiveTimeDay
from employee.models import Employee

logger = logging.getLogger(__name__)


def _employee_for(block, by_badge, by_email):
    ext = (block.get("external_id") or "").strip()
    email = (block.get("email") or "").strip().lower()
    if ext and ext in by_badge:
        return by_badge[ext]
    # The tracker admin may also have typed the employee e-mail as the external id.
    return by_email.get(email) or by_email.get(ext.lower())


def _aware(epoch):
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc) if epoch else None


def sync_range(start, end):
    """Fetch start..end from the tracker and upsert. Returns (rows_saved, unmatched_names)."""
    blocks = client.fetch_all(start, end)
    employees = list(
        Employee.objects.filter(is_active=True).only("id", "email", "badge_id")
    )
    by_badge = {e.badge_id.strip(): e for e in employees if e.badge_id}
    by_email = {e.email.strip().lower(): e for e in employees if e.email}
    rows, unmatched = [], []
    for block in blocks:
        info = block.get("employee", {})
        employee = _employee_for(info, by_badge, by_email)
        if employee is None:
            unmatched.append(info.get("name") or info.get("email") or "?")
            continue
        status = (block.get("agent") or {}).get("status", "")
        for day in block.get("days", []):
            rows.append(
                ActiveTimeDay(
                    employee_id=employee,
                    date=datetime.date.fromisoformat(day["date"]),
                    active_seconds=int(day.get("active_seconds") or 0),
                    tracked_seconds=int(day.get("tracked_seconds") or 0),
                    first_seen=_aware(day.get("first_seen")),
                    last_seen=_aware(day.get("last_seen")),
                    agent_status=status[:30],
                    tracker_employee_id=info.get("id"),
                    synced_at=timezone.now(),
                )
            )
    if rows:
        ActiveTimeDay.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["employee_id", "date"],
            update_fields=[
                "active_seconds",
                "tracked_seconds",
                "first_seen",
                "last_seen",
                "agent_status",
                "tracker_employee_id",
                "synced_at",
            ],
        )
    return len(rows), unmatched


def sync_recent(days=2):
    today = datetime.date.today()
    return sync_range(today - datetime.timedelta(days=days - 1), today)
