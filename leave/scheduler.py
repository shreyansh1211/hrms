from datetime import datetime

from horilla.scheduling import register_job
from horilla.signals import post_scheduler, pre_scheduler


def leave_reset():
    pre_scheduler.send(sender=leave_reset)
    from leave.models import LeaveType

    today = datetime.now()
    today_date = today.date()
    leave_types = LeaveType.objects.filter(reset=True)
    # Looping through filtered leave types with reset is true
    for leave_type in leave_types:
        # Looping through all available leaves
        available_leaves = leave_type.employee_available_leave.all()

        for available_leave in available_leaves:
            reset_date = available_leave.reset_date
            expired_date = available_leave.expired_date
            # <= (not ==): the job only runs every few hours inside a
            # separate run_scheduler process, so a reset_date that's
            # already in the past (a missed tick) must still be caught
            # here -- otherwise that employee's leave never resets again.
            # Matches the expired_date check right below, which already
            # uses <=.
            if reset_date and reset_date <= today_date:
                available_leave.update_carryforward()
                # new_reset_date = available_leave.set_reset_date(assigned_date=today_date,available_leave = available_leave)
                new_reset_date = available_leave.set_reset_date(
                    assigned_date=today_date, available_leave=available_leave
                )
                available_leave.reset_date = new_reset_date
                available_leave._change_reason = "Leave reset"
                available_leave.save()
            if expired_date and expired_date <= today_date:
                new_expired_date = available_leave.set_expired_date(
                    available_leave=available_leave, assigned_date=today_date
                )
                available_leave.expired_date = new_expired_date
                available_leave._change_reason = "Carryforward expired"
                available_leave.save()

        if (
            leave_type.carryforward_expire_date
            and leave_type.carryforward_expire_date <= today_date
        ):
            leave_type.carryforward_expire_date = leave_type.set_expired_date(
                today_date
            )
            leave_type.save()
    post_scheduler.send(
        sender=leave_reset,
        **{
            "today": today,
            "today_date": today_date,
            "leave_types": leave_types,
        }
    )


ACCRUAL_LEAVE_TYPES = ("Sick Leave", "Privilege Leave", "Casual Leave")
ACCRUAL_DAYS = 2
ACCRUAL_EVERY_MONTHS = 4


def leave_accrual():
    """
    Credit ACCRUAL_DAYS to SL/PL/CL every ACCRUAL_EVERY_MONTHS months,
    counted from the day each employee was assigned the leave type.

    These leave types have reset=False, so the built-in leave_reset job never
    touches them; AvailableLeave.reset_date is reused here as the date of the
    next credit. Unused leave accumulates.
    """
    from dateutil.relativedelta import relativedelta

    from leave.models import AvailableLeave

    today = datetime.now().date()
    for available in AvailableLeave.objects.filter(
        leave_type_id__name__in=ACCRUAL_LEAVE_TYPES
    ).select_related("leave_type_id"):
        if available.reset_date is None:
            available.reset_date = available.assigned_date + relativedelta(
                months=ACCRUAL_EVERY_MONTHS
            )
            available.save()
            continue
        credited = False
        while available.reset_date <= today:
            available.available_days += ACCRUAL_DAYS
            available.reset_date += relativedelta(months=ACCRUAL_EVERY_MONTHS)
            credited = True
        if credited:
            available._change_reason = "Four-monthly leave credit"
            available.save()


register_job(leave_reset, "interval", hours=4)
register_job(leave_accrual, "interval", hours=6, job_id="leave_accrual")
