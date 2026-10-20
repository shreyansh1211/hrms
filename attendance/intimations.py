"""
Attendance intimations: late check-in / early check-out beyond the grace
period, and automatic sign-outs, that the employee must explain to their
reporting manager from inside Infisetu MIS.

Nothing here may break check-in or check-out: the hooks called from the clock
views swallow and log every error.
"""

import datetime
import logging

from django.utils import timezone

from attendance.models import (
    Attendance,
    AttendanceActivity,
    AttendanceIntimation,
    AttendanceLateComeEarlyOut,
)
from base.branded_email import send_branded
from base.models import EmployeeShiftSchedule

logger = logging.getLogger(__name__)

GRACE = datetime.timedelta(minutes=30)


# --- shift window ---------------------------------------------------------
def shift_window(attendance):
    """(start, end) naive local datetimes of the shift this attendance belongs to."""
    if not attendance.shift_id_id or not attendance.attendance_day_id:
        return None
    schedule = EmployeeShiftSchedule.objects.filter(
        shift_id=attendance.shift_id_id, day=attendance.attendance_day_id
    ).first()
    if not schedule or not schedule.start_time or not schedule.end_time:
        return None
    day = attendance.attendance_date
    start = datetime.datetime.combine(day, schedule.start_time)
    end_day = day + datetime.timedelta(days=1) if schedule.end_time <= schedule.start_time else day
    end = datetime.datetime.combine(end_day, schedule.end_time)
    return start, end


def _to_time(value):
    if isinstance(value, datetime.time):
        return value
    text = str(value)
    for fmt in ("%H:%M:%S", "%H:%M", "%H:%M:%S.%f"):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised time {value!r}")


def _fmt(dt_value):
    return dt_value.strftime("%d %b %Y, %I:%M %p").replace(" 0", " ")


def _minutes(delta):
    return int(delta.total_seconds() // 60)


# --- creation hooks -----------------------------------------------------------
def _create(attendance, kind, detail, mail_key, recorded, summary, mail_kind):
    obj, created = AttendanceIntimation.objects.get_or_create(
        attendance_id=attendance,
        kind=kind,
        defaults={
            "employee_id": attendance.employee_id,
            "detail": detail,
        },
    )
    if created:
        _notify_open(obj, mail_key, recorded, summary, mail_kind)
    return obj


def _notify_open(intimation, mail_key, recorded, summary, kind_label):
    employee = intimation.employee_id
    window = shift_window(intimation.attendance_id)
    shift_text = (
        f"{window[0]:%I:%M %p} - {window[1]:%I:%M %p}".replace(" 0", " ")
        if window
        else "-"
    )
    send_branded(
        mail_key,
        employee.get_email(),
        {
            "employee": employee.get_full_name(),
            "date": intimation.attendance_id.attendance_date.strftime("%d %b %Y"),
            "kind": kind_label,
            "summary": summary,
            "shift": shift_text,
            "recorded": recorded,
            "hours": 12,
            "out_time": recorded,
        },
    )


def check_late_in(attendance):
    """Call after a check-in. Only the first check-in of the day can be late."""
    try:
        if AttendanceActivity.objects.filter(
            employee_id=attendance.employee_id,
            attendance_date=attendance.attendance_date,
        ).count() > 1:
            return None
        window = shift_window(attendance)
        if not window or not attendance.attendance_clock_in:
            return None
        start, _end = window
        clock_in = datetime.datetime.combine(
            attendance.attendance_clock_in_date or attendance.attendance_date,
            _to_time(attendance.attendance_clock_in),
        )
        late_by = clock_in - start
        if late_by <= GRACE:
            return None
        minutes = _minutes(late_by)
        detail = (
            f"Your shift starts at {start:%I:%M %p}. You checked in at "
            f"{clock_in:%I:%M %p}, which is {minutes} minutes after the start "
            f"(grace period is {_minutes(GRACE)} minutes)."
        ).replace(" 0", " ")
        return _create(
            attendance,
            "late_in",
            detail,
            "Attendance Intimation - Action Required",
            f"Checked in at {clock_in:%I:%M %p}".replace(" 0", " "),
            detail,
            "Late check-in",
        )
    except Exception:
        logger.exception("late check-in intimation failed")
        return None


def clear_open_early_out(attendance):
    """A new check-in cancels an early check-out that nobody has responded to yet."""
    try:
        AttendanceIntimation.objects.filter(
            attendance_id=attendance, kind="early_out", status="open"
        ).delete()
    except Exception:
        logger.exception("clearing early check-out intimation failed")


def check_early_out(attendance):
    """Call after a check-out."""
    try:
        window = shift_window(attendance)
        if (
            not window
            or not attendance.attendance_clock_out
            or not attendance.attendance_clock_out_date
        ):
            return None
        _start, end = window
        clock_out = datetime.datetime.combine(
            attendance.attendance_clock_out_date, _to_time(attendance.attendance_clock_out)
        )
        early_by = end - clock_out
        if early_by <= GRACE:
            return None
        minutes = _minutes(early_by)
        detail = (
            f"Your shift ends at {end:%I:%M %p}. You checked out at "
            f"{clock_out:%I:%M %p}, which is {minutes} minutes before the end "
            f"(grace period is {_minutes(GRACE)} minutes)."
        ).replace(" 0", " ")
        return _create(
            attendance,
            "early_out",
            detail,
            "Attendance Intimation - Action Required",
            f"Checked out at {clock_out:%I:%M %p}".replace(" 0", " "),
            detail,
            "Early check-out",
        )
    except Exception:
        logger.exception("early check-out intimation failed")
        return None


def open_missed_sign_out(attendance, out_datetime):
    """Called by the auto sign-out job. Emails the employee via the 'Missed Sign-out' template."""
    try:
        obj, created = AttendanceIntimation.objects.get_or_create(
            attendance_id=attendance,
            kind="missed_sign_out",
            defaults={
                "employee_id": attendance.employee_id,
                "detail": (
                    "You did not sign out. The system signed you out automatically at "
                    f"{_fmt(out_datetime)}, 12 hours after your first check-in. "
                    "Enter your actual sign-out time so your attendance is correct."
                ),
            },
        )
        if created:
            employee = attendance.employee_id
            send_branded(
                "Missed Sign-out Notice",
                employee.get_email(),
                {
                    "employee": employee.get_full_name(),
                    "date": attendance.attendance_date.strftime("%d %b %Y"),
                    "hours": 12,
                    "out_time": _fmt(out_datetime),
                },
            )
        return obj
    except Exception:
        logger.exception("missed sign-out intimation failed")
        return None


# --- attendance recalculation -----------------------------------------------------
def recalculate_attendance(attendance, out_datetime):
    """
    Recompute worked hours, overtime and validation for ``attendance`` after its
    final sign-out became ``out_datetime`` (every activity must already be closed).
    """
    from attendance.methods.utils import (
        activity_datetime,
        format_time,
        overtime_calculation,
    )
    from attendance.views.views import attendance_validate

    duration = 0
    for activity in AttendanceActivity.objects.filter(
        employee_id=attendance.employee_id, attendance_date=attendance.attendance_date
    ):
        in_dt, out_dt = activity_datetime(activity)
        duration += int((out_dt - in_dt).total_seconds())
    local_out = timezone.localtime(out_datetime) if timezone.is_aware(out_datetime) else out_datetime
    attendance.attendance_clock_out = local_out.strftime("%H:%M:00")
    attendance.attendance_clock_out_date = local_out.date()
    attendance.attendance_worked_hour = format_time(duration)
    attendance.attendance_overtime = overtime_calculation(attendance)
    attendance.attendance_validated = attendance_validate(attendance)
    attendance.save()
    return attendance


# --- employee / manager actions ---------------------------------------------------------
def can_review(user, intimation):
    if user.is_superuser or user.has_perm("attendance.change_attendance"):
        return True
    manager = intimation.employee_id.employee_work_info.reporting_manager_id
    me = getattr(user, "employee_get", None)
    return bool(manager and me and manager.pk == me.pk)


def submit(intimation, comment, proof=None, actual_out_time=None):
    """Employee answers an open (or rejected) intimation."""
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("Please add a comment explaining what happened.")
    if intimation.kind == "missed_sign_out":
        if actual_out_time is None:
            raise ValueError("Please enter your actual sign-out time.")
        attendance = intimation.attendance_id
        clock_in = datetime.datetime.combine(
            attendance.attendance_clock_in_date or attendance.attendance_date,
            _to_time(attendance.attendance_clock_in),
        )
        out = datetime.datetime.combine(clock_in.date(), actual_out_time)
        if out <= clock_in:
            out += datetime.timedelta(days=1)
        if out - clock_in > datetime.timedelta(hours=12):
            raise ValueError(
                "The actual sign-out must be within 12 hours of your check-in."
            )
        intimation.requested_out = timezone.make_aware(out)
    intimation.comment = comment
    if proof:
        intimation.proof = proof
    intimation.status = "submitted"
    intimation.submitted_at = timezone.now()
    intimation.save()
    manager = intimation.employee_id.employee_work_info.reporting_manager_id
    if manager:
        send_branded(
            "Attendance Intimation - Submitted",
            manager.get_email(),
            {
                "employee": intimation.employee_id.get_full_name(),
                "kind": intimation.get_kind_display(),
                "date": intimation.attendance_id.attendance_date.strftime("%d %b %Y"),
                "comment": intimation.comment,
                "requested_out": _fmt(intimation.requested_out)
                if intimation.requested_out
                else "-",
            },
        )
    return intimation


def decide(intimation, approve, reviewer, manager_comment=""):
    """Manager approves or rejects a submitted intimation."""
    intimation.status = "approved" if approve else "rejected"
    intimation.manager_comment = (manager_comment or "").strip()
    intimation.reviewed_by = getattr(reviewer, "employee_get", None)
    intimation.reviewed_at = timezone.now()
    intimation.save()
    attendance = intimation.attendance_id
    if approve:
        if intimation.kind == "missed_sign_out" and intimation.requested_out:
            activity = (
                AttendanceActivity.objects.filter(
                    employee_id=attendance.employee_id,
                    attendance_date=attendance.attendance_date,
                )
                .order_by("id")
                .last()
            )
            if activity:
                local_out = timezone.localtime(intimation.requested_out)
                activity.clock_out = local_out.time()
                activity.clock_out_date = local_out.date()
                activity.out_datetime = intimation.requested_out
                activity.save()
            recalculate_attendance(attendance, intimation.requested_out)
        elif intimation.kind in ("late_in", "early_out"):
            # Excused: drop Horilla's own late/early report for the same day.
            AttendanceLateComeEarlyOut.objects.filter(
                attendance_id=attendance,
                type="late_come" if intimation.kind == "late_in" else "early_out",
            ).delete()
    send_branded(
        "Attendance Intimation - Decision",
        intimation.employee_id.get_email(),
        {
            "employee": intimation.employee_id.get_full_name(),
            "kind": intimation.get_kind_display(),
            "date": attendance.attendance_date.strftime("%d %b %Y"),
            "status": intimation.get_status_display().lower(),
            "manager_comment": intimation.manager_comment or "-",
        },
    )
    return intimation
