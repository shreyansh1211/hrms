from datetime import date

from horilla.scheduling import register_job
from horilla.signals import post_scheduler, pre_scheduler


def leave_reset():
    pre_scheduler.send(sender=leave_reset)
    from datetime import datetime

    from leave.models import LeaveType

    today = datetime.now()
    today_date = today.date()
    leave_types = LeaveType.objects.filter(reset=True)
    for leave_type in leave_types:
        available_leaves = leave_type.employee_available_leave.all()
        for available_leave in available_leaves:
            reset_date = available_leave.reset_date
            expired_date = available_leave.expired_date
            if reset_date and reset_date <= today_date:
                available_leave.update_carryforward()
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
            leave_type.carryforward_expire_date = leave_type.set_expired_date(today_date)
            leave_type.save()
    post_scheduler.send(
        sender=leave_reset,
        **{
            "today": today,
            "today_date": today_date,
            "leave_types": leave_types,
        },
    )


# ---------------------------------------------------------------------------
# Four-monthly cycle credit jobs (Apr 1, Aug 1, Dec 1) + year-end (Mar 31)
# ---------------------------------------------------------------------------


def _cycle_credit_job():
    """Called by all three cron triggers. Reads today's date internally."""
    from leave.credit_service import apply_cycle_credits

    result = apply_cycle_credits()
    if result["errors"]:
        import logging

        logging.getLogger(__name__).error(
            "Cycle credit errors: %s", result["errors"]
        )


def _year_end_job():
    """Called on 31 March. Applies carry-forward rules before Cycle 1 opens."""
    from leave.credit_service import apply_year_end_carryforward

    result = apply_year_end_carryforward()
    if result["errors"]:
        import logging

        logging.getLogger(__name__).error(
            "Year-end carry-forward errors: %s", result["errors"]
        )


register_job(leave_reset, "interval", hours=4)

# Cycle 1: 1 April — also the new leave year start
register_job(
    _cycle_credit_job,
    "cron",
    month=4,
    day=1,
    hour=1,
    minute=0,
    job_id="leave.credit_cycle1",
)

# Cycle 2: 1 August
register_job(
    _cycle_credit_job,
    "cron",
    month=8,
    day=1,
    hour=1,
    minute=0,
    job_id="leave.credit_cycle2",
)

# Cycle 3: 1 December
register_job(
    _cycle_credit_job,
    "cron",
    month=12,
    day=1,
    hour=1,
    minute=0,
    job_id="leave.credit_cycle3",
)

# Year-end: 31 March (carry-forward before Cycle 1)
register_job(
    _year_end_job,
    "cron",
    month=3,
    day=31,
    hour=23,
    minute=0,
    job_id="leave.year_end",
)
