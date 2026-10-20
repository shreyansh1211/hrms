"""
Three times per employee:

* In time      - attendance (check-in to check-out, from Horilla)
* Active time  - keyboard/mouse activity measured by the desk agent (tracker)
* Project time - hours logged on project timesheets

Employees see their own totals only (dashboard panel). People with the
"view active time" permission also get the team table, with a link to the
tracker console for the detailed data.
"""

import datetime
from collections import defaultdict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from activity_tracker import client, sync
from activity_tracker.models import ActiveTimeDay
from employee.models import Employee

PERMISSION = "activity_tracker.view_activetimeday"


def fmt(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def _dates(request):
    today = datetime.date.today()

    def parse(name, default):
        try:
            return datetime.date.fromisoformat(request.GET.get(name, ""))
        except ValueError:
            return default

    start = parse("from_date", today)
    end = parse("to_date", start if request.GET.get("from_date") else today)
    if end < start:
        end = start
    if (end - start).days > 92:
        start = end - datetime.timedelta(days=92)
    return start, end


def totals(employee_ids, start, end):
    """{employee_id: {"in": s, "active": s, "project": s, "tracked": s, ...}} for the period."""
    from attendance.models import Attendance, AttendanceActivity
    from employee.methods.duration_methods import strtime_seconds
    from project.models import TimeSheet

    out = defaultdict(lambda: {"in": 0, "active": 0, "project": 0, "tracked": 0,
                               "first_seen": None, "last_seen": None, "status": ""})
    for row in (
        Attendance.objects.filter(
            employee_id__in=employee_ids, attendance_date__range=(start, end)
        )
        .values("employee_id")
        .annotate(total=Sum("at_work_second"))
    ):
        out[row["employee_id"]]["in"] += row["total"] or 0
    # A session that is still open has not reached at_work_second yet.
    if start <= datetime.date.today() <= end:
        now = timezone.now()
        for act in AttendanceActivity.objects.filter(
            employee_id__in=employee_ids, clock_out__isnull=True, in_datetime__isnull=False
        ).values("employee_id", "in_datetime"):
            out[act["employee_id"]]["in"] += max(
                0, int((now - act["in_datetime"]).total_seconds())
            )
    for sheet in TimeSheet.objects.filter(
        employee_id__in=employee_ids, date__range=(start, end)
    ).values("employee_id", "time_spent"):
        try:
            out[sheet["employee_id"]]["project"] += strtime_seconds(
                sheet["time_spent"] or "0:0"
            )
        except (ValueError, AttributeError):
            continue
    for day in ActiveTimeDay.objects.filter(
        employee_id__in=employee_ids, date__range=(start, end)
    ):
        row = out[day.employee_id_id]
        row["active"] += day.active_seconds
        row["tracked"] += day.tracked_seconds
        row["status"] = row["status"] or day.agent_status
        if day.first_seen and (row["first_seen"] is None or day.first_seen < row["first_seen"]):
            row["first_seen"] = day.first_seen
        if day.last_seen and (row["last_seen"] is None or day.last_seen > row["last_seen"]):
            row["last_seen"] = day.last_seen
    return out


@login_required
def my_time(request):
    """JSON for the dashboard panel: the signed-in employee's own three totals."""
    employee = getattr(request.user, "employee_get", None)
    if employee is None:
        return JsonResponse({"enabled": False})
    start, end = _dates(request)
    today = datetime.date.today()
    period = totals([employee.pk], start, end)[employee.pk]
    day = totals([employee.pk], today, today)[employee.pk]
    return JsonResponse(
        {
            "enabled": client.configured() or ActiveTimeDay.objects.filter(employee_id=employee).exists(),
            "period": {k: fmt(period[k]) for k in ("in", "active", "project")},
            "today": {k: fmt(day[k]) for k in ("in", "active", "project")},
        }
    )


def _can_view_team(user):
    return user.is_superuser or user.has_perm(PERMISSION)


@login_required
def team(request):
    if not _can_view_team(request.user):
        return HttpResponseForbidden("You do not have access to team active time.")
    start, end = _dates(request)
    employees = list(
        Employee.objects.filter(is_active=True)
        .select_related("employee_work_info__department_id")
        .order_by("employee_first_name")
    )
    data = totals([e.pk for e in employees], start, end)
    console = getattr(settings, "ACTIVITY_TRACKER_CONSOLE_URL", "").rstrip("/")
    tracker_ids = dict(
        ActiveTimeDay.objects.filter(employee_id__in=[e.pk for e in employees])
        .exclude(tracker_employee_id=None)
        .values_list("employee_id", "tracker_employee_id")
    )
    rows = []
    for e in employees:
        t = data[e.pk]
        ratio = round(100 * t["active"] / t["in"]) if t["in"] else None
        rows.append(
            {
                "employee": e,
                "in": fmt(t["in"]),
                "active": fmt(t["active"]),
                "project": fmt(t["project"]),
                "tracked": fmt(t["tracked"]),
                "ratio": ratio,
                "low": ratio is not None and ratio < 50,
                "status": t["status"] or "-",
                "last_seen": t["last_seen"],
                "link": f"{console}/employees/{tracker_ids[e.pk]}"
                if console and e.pk in tracker_ids
                else "",
                "has_data": bool(t["active"] or t["tracked"]),
            }
        )
    return render(
        request,
        "activity_tracker/team.html",
        {
            "rows": rows,
            "from_date": start,
            "to_date": end,
            "configured": client.configured(),
            "console": console,
        },
    )


@login_required
@require_http_methods(["POST"])
def sync_now(request):
    if not _can_view_team(request.user):
        return HttpResponseForbidden("You do not have access.")
    try:
        saved, unmatched = sync.sync_recent(3)
        messages.success(request, f"Synced {saved} day record(s) from the activity tracker.")
        if unmatched:
            messages.warning(
                request,
                "No matching employee in the HRMS for: "
                + ", ".join(unmatched[:5])
                + ". Set the tracker employee's external id to the HRMS badge id or use the same e-mail.",
            )
    except client.TrackerError as exc:
        messages.error(request, str(exc))
    return redirect("activity-team")
