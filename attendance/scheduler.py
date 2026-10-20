import datetime
from datetime import timedelta

from django.utils import timezone

from base.backends import logger
from horilla.scheduling import register_job


def auto_punch_out():
    from attendance.methods.utils import Request
    from attendance.models import Attendance, AttendanceActivity
    from attendance.views.clock_in_out import clock_out
    from base.models import EmployeeShiftSchedule

    automatic_check_out_shifts = EmployeeShiftSchedule.objects.filter(
        is_auto_punch_out_enabled=True
    )

    for shift_schedule in automatic_check_out_shifts:
        activities = AttendanceActivity.objects.filter(
            shift_day=shift_schedule.day,
            clock_out_date=None,
            clock_out=None,
        ).order_by("-created_at")

        for activity in activities:
            attendance = Attendance.objects.filter(
                employee_id=activity.employee_id,
                attendance_clock_out=None,
                attendance_clock_out_date=None,
                shift_id=shift_schedule.shift_id,
                attendance_day=shift_schedule.day,
                attendance_date=activity.attendance_date,
            ).first()

            if attendance:
                date = activity.attendance_date
                if (
                    shift_schedule.is_night_shift
                    and shift_schedule.start_time
                    and shift_schedule.end_time
                    and shift_schedule.start_time > shift_schedule.end_time
                ):
                    date += timedelta(days=1)

                combined_datetime = timezone.make_aware(
                    datetime.datetime.combine(date, shift_schedule.auto_punch_out_time)
                )

                if combined_datetime < timezone.now():
                    try:
                        clock_out(
                            Request(
                                user=attendance.employee_id.employee_user_id,
                                date=date,
                                time=shift_schedule.auto_punch_out_time,
                                datetime=combined_datetime,
                            )
                        )
                    except Exception as e:
                        logger.error(f"auto_punch_out error: {e}")


MAX_OPEN_SESSION_HOURS = 12


def _first_check_in_datetime(activity):
    """Aware datetime of an activity's check-in (falls back to date + time)."""
    if activity.in_datetime:
        return timezone.localtime(activity.in_datetime)
    if activity.clock_in_date and activity.clock_in:
        return timezone.make_aware(
            datetime.datetime.combine(activity.clock_in_date, activity.clock_in)
        )
    return None


def auto_sign_out_missed():
    """
    Sign out anyone still checked in MAX_OPEN_SESSION_HOURS after their first
    check-in of the attendance day, stamp the sign-out at exactly that limit,
    and email the employee. Independent of the shift based auto_punch_out.
    """
    from attendance.intimations import open_missed_sign_out, recalculate_attendance
    from attendance.models import Attendance, AttendanceActivity

    now = timezone.now()
    limit = timedelta(hours=MAX_OPEN_SESSION_HOURS)

    open_pairs = (
        AttendanceActivity.objects.filter(clock_out__isnull=True)
        .values_list("employee_id", "attendance_date")
        .distinct()
    )
    for employee_pk, attendance_date in open_pairs:
        try:
            activities = AttendanceActivity.objects.filter(
                employee_id=employee_pk, attendance_date=attendance_date
            ).order_by("id")
            first_in = None
            for activity in activities:
                candidate = _first_check_in_datetime(activity)
                if candidate and (first_in is None or candidate < first_in):
                    first_in = candidate
            if first_in is None or now < first_in + limit:
                continue

            out_datetime = first_in + limit
            attendance = Attendance.objects.filter(
                employee_id=employee_pk, attendance_date=attendance_date
            ).first()
            if attendance is None:
                continue

            for activity in activities.filter(clock_out__isnull=True):
                activity_in = _first_check_in_datetime(activity)
                # A re-check-in made after the limit is closed at its own
                # check-in time, so it never has negative duration.
                activity_out = max(out_datetime, activity_in or out_datetime)
                activity.clock_out = activity_out
                activity.clock_out_date = activity_out.date()
                activity.out_datetime = activity_out
                activity.save()

            recalculate_attendance(attendance, out_datetime)
            # Shows up under Attendance -> Intimations and e-mails the employee.
            open_missed_sign_out(attendance, out_datetime)
        except Exception:
            logger.exception(
                "auto_sign_out_missed failed for employee_id=%s date=%s",
                employee_pk,
                attendance_date,
            )


def create_work_record():
    from attendance.models import WorkRecords
    from employee.models import Employee

    date = datetime.date.today()
    work_records = WorkRecords.objects.filter(date=date).values_list(
        "employee_id", flat=True
    )
    employees = Employee.objects.exclude(id__in=work_records)
    records_to_create = []

    for employee in employees:
        try:
            shift_schedule = employee.get_shift_schedule()
            if shift_schedule is None:
                continue

            shift = employee.get_shift()
            record = WorkRecords(
                employee_id=employee,
                date=date,
                work_record_type="DFT",
                shift_id=shift,
                message="",
            )
            records_to_create.append(record)
        except Exception as e:
            # Employee.__str__ is "Name (BADGE)", so interpolating the
            # object writes a real name into the log. The id is enough to
            # find the row, and logger.exception keeps the traceback.
            logger.exception(
                "Error preparing work record for employee_id=%s",
                getattr(employee, "pk", employee),
            )

    if records_to_create:
        try:
            WorkRecords.objects.bulk_create(records_to_create, ignore_conflicts=True)
        except Exception as e:
            logger.error(f"Failed to bulk create work records: {e}")


register_job(create_work_record, "interval", minutes=30, misfire_grace_time=3600 * 3)
register_job(
    create_work_record,
    "cron",
    job_id="create_daily_work_record",
    hour=0,
    minute=30,
    misfire_grace_time=3600 * 9,
)
register_job(
    auto_punch_out,
    "interval",
    job_id="auto_punch_out",
    minutes=5,
    misfire_grace_time=600,
)
register_job(
    auto_sign_out_missed,
    "interval",
    job_id="auto_sign_out_missed",
    minutes=10,
    misfire_grace_time=600,
)
