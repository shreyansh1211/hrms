"""
leave/credit_service.py

Core business logic for the four-monthly leave credit system.
Called by the scheduler cron jobs and the management command.
"""

import logging
import math
from datetime import date

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

# Cycle definitions: cycle_number -> start/end month+day
# Cycle 3 ends on March 31 of the NEXT calendar year
CYCLE_DATES = {
    "1": dict(start_month=4, start_day=1, end_month=7, end_day=31),
    "2": dict(start_month=8, start_day=1, end_month=11, end_day=30),
    "3": dict(start_month=12, start_day=1, end_month=3, end_day=31),
}


def get_leave_year(d: date) -> str:
    """
    Leave year runs Apr 1 → Mar 31.
    Apr 1 2025 – Mar 31 2026  →  "2025-26"
    """
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    return f"{d.year - 1}-{str(d.year)[2:]}"


def round_half_up(x: float) -> int:
    """Round to nearest int: 0.5 and above rounds up (not banker's rounding)."""
    return math.floor(x + 0.5)


def get_cycle_for_date(d: date) -> str | None:
    """Return cycle number for a credit date, or None if today is not a credit date."""
    for cycle, info in CYCLE_DATES.items():
        if d.month == info["start_month"] and d.day == info["start_day"]:
            return cycle
    return None


def get_cycle_start_end(cycle: str, credit_date: date) -> tuple[date, date]:
    """Return (cycle_start, cycle_end) for the cycle being credited on credit_date."""
    if cycle == "1":
        return date(credit_date.year, 4, 1), date(credit_date.year, 7, 31)
    if cycle == "2":
        return date(credit_date.year, 8, 1), date(credit_date.year, 11, 30)
    # cycle == "3": Dec 1 → Mar 31 next year
    return date(credit_date.year, 12, 1), date(credit_date.year + 1, 3, 31)


def is_trainee(employee) -> bool:
    """True if the employee's employment type is 'Trainee' (case-insensitive)."""
    work_info = getattr(employee, "employee_work_info", None)
    if work_info is None:
        return False
    emp_type = getattr(work_info, "employee_type_id", None)
    if emp_type is None:
        return False
    return str(emp_type.employee_type).strip().lower() == "trainee"


def compute_prorate_days(
    days_to_credit: float,
    join_date: date,
    cycle_start: date,
    cycle_end: date,
) -> int:
    """
    Pro-rata days for a mid-cycle joiner.
    remaining_days / total_days * days_to_credit, then round_half_up.
    """
    effective_start = max(join_date, cycle_start)
    remaining = (cycle_end - effective_start).days + 1
    total = (cycle_end - cycle_start).days + 1
    if remaining <= 0:
        return 0
    return round_half_up(days_to_credit * remaining / total)


def _send_credit_notification(employee, leave_type, days: float, credit_date: date) -> None:
    """Send an in-app notification to the employee (non-fatal on failure)."""
    try:
        from django.urls import reverse
        from django.utils.translation import gettext_noop

        from horilla_auth.models import HorillaUser
        from notifications.signals import notify

        bot = HorillaUser.objects.filter(username="Horilla Bot").only("id").first()
        recipient = getattr(employee, "employee_user_id", None)
        if bot and recipient:
            notify.send(
                bot,
                recipient=recipient,
                verb=gettext_noop(
                    "%(days)s day(s) of %(leave_type)s credited for %(date)s cycle."
                ),
                verb_params={
                    "days": str(int(days) if days == int(days) else days),
                    "leave_type": str(leave_type),
                    "date": str(credit_date),
                },
                redirect=reverse("user-request-view"),
                label="System",
                icon="information",
            )
    except Exception:
        logger.warning(
            "Could not send credit notification to %s", employee, exc_info=True
        )


def apply_cycle_credits(
    credit_date: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Credit leave for all active, non-trainee employees on a cycle credit date.

    Safe to call multiple times (idempotent):
    - Application-level check first (fast path)
    - DB UniqueConstraint as final guard against race conditions

    Returns dict: {"credited": [...], "skipped": [...], "errors": [...]}
    """
    from leave.models import AvailableLeave, LeaveCycleLog, LeaveCyclePolicy

    if credit_date is None:
        credit_date = date.today()

    cycle = get_cycle_for_date(credit_date)
    if cycle is None:
        logger.info(
            "apply_cycle_credits: %s is not a cycle credit date — no action.", credit_date
        )
        return {"credited": [], "skipped": [], "errors": []}

    leave_year = get_leave_year(credit_date)
    cycle_start, cycle_end = get_cycle_start_end(cycle, credit_date)

    policies = LeaveCyclePolicy.objects.filter(
        credit_month=credit_date.month,
        credit_day=credit_date.day,
        is_active=True,
    ).select_related("leave_type_id", "company_id")

    if not policies.exists():
        logger.info("apply_cycle_credits: No active policies for %s — no action.", credit_date)
        return {"credited": [], "skipped": [], "errors": []}

    credited, skipped, errors = [], [], []

    for policy in policies:
        qs = AvailableLeave.objects.filter(
            leave_type_id=policy.leave_type_id,
            employee_id__is_active=True,
        ).select_related(
            "employee_id",
            "employee_id__employee_work_info",
            "employee_id__employee_work_info__employee_type_id",
        )
        if policy.company_id_id:
            qs = qs.filter(
                employee_id__employee_work_info__company_id=policy.company_id
            )

        for al in qs:
            emp = al.employee_id

            if is_trainee(emp):
                skipped.append(f"{emp} | {policy.leave_type_id} | Trainee — skipped")
                continue

            # Fast-path idempotency check
            if LeaveCycleLog.objects.filter(
                employee_id=emp,
                leave_type_id=policy.leave_type_id,
                leave_year=leave_year,
                cycle_number=cycle,
            ).exists():
                skipped.append(
                    f"{emp} | {policy.leave_type_id} | Already credited this cycle"
                )
                continue

            # Determine credit amount (pro-rata for mid-cycle joiners)
            join_date = None
            work_info = getattr(emp, "employee_work_info", None)
            if work_info:
                join_date = getattr(work_info, "date_joining", None)

            if join_date and join_date > cycle_start:
                days = compute_prorate_days(
                    policy.days_to_credit, join_date, cycle_start, cycle_end
                )
                if days <= 0:
                    skipped.append(
                        f"{emp} | {policy.leave_type_id} | Pro-rata = 0 — skipped"
                    )
                    continue
            else:
                days = round_half_up(policy.days_to_credit)

            if dry_run:
                credited.append(
                    f"[DRY RUN] {emp} | {policy.leave_type_id} | +{days} days"
                )
                continue

            try:
                with transaction.atomic():
                    al_locked = AvailableLeave.objects.select_for_update().get(pk=al.pk)
                    al_locked.available_days = round(al_locked.available_days + days, 2)
                    al_locked._change_reason = (
                        f"Cycle {cycle} credit ({leave_year})"
                    )
                    al_locked.save()

                    LeaveCycleLog.objects.create(
                        employee_id=emp,
                        leave_type_id=policy.leave_type_id,
                        policy_id=policy,
                        leave_year=leave_year,
                        cycle_number=cycle,
                        days_credited=days,
                        credited_on=credit_date,
                        source="scheduler",
                    )

                _send_credit_notification(emp, policy.leave_type_id, days, credit_date)
                credited.append(f"{emp} | {policy.leave_type_id} | +{days} days")

            except IntegrityError:
                # Race condition: another process already credited this employee
                skipped.append(
                    f"{emp} | {policy.leave_type_id} | Concurrent credit — skipped"
                )
            except Exception as exc:
                logger.exception(
                    "Error crediting %s for %s", emp, policy.leave_type_id
                )
                errors.append(f"{emp} | {policy.leave_type_id} | {exc}")

    logger.info(
        "Cycle %s credits (%s): %d credited, %d skipped, %d errors",
        cycle,
        credit_date,
        len(credited),
        len(skipped),
        len(errors),
    )
    return {"credited": credited, "skipped": skipped, "errors": errors}


def apply_year_end_carryforward(
    as_of_date: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Year-end carry-forward (run on 31 March, before Cycle 1 credits on 1 April).

    For each LeaveCyclePolicy cycle_number="1":
    - carryforward_percent=100  → carry full remaining balance
    - carryforward_percent=50   → carry 50 % (round_half_up) of remaining balance
    - carryforward_percent=0    → zero out
    """
    from leave.models import AvailableLeave, LeaveCyclePolicy

    if as_of_date is None:
        as_of_date = date.today()

    leave_year = get_leave_year(as_of_date)
    results: dict[str, list] = {"carried": [], "zeroed": [], "errors": []}

    # Use cycle 1 policy to get the carry-forward % per leave type
    policies = LeaveCyclePolicy.objects.filter(
        is_active=True, cycle_number="1"
    ).select_related("leave_type_id")

    for policy in policies:
        qs = AvailableLeave.objects.filter(
            leave_type_id=policy.leave_type_id,
            employee_id__is_active=True,
        )
        if policy.company_id_id:
            qs = qs.filter(
                employee_id__employee_work_info__company_id=policy.company_id
            )

        pct = policy.carryforward_percent / 100.0

        for al in qs:
            total = round(al.available_days + al.carryforward_days, 2)
            carry = round_half_up(total * pct) if pct > 0 else 0

            tag = (
                f"{al.employee_id} | {policy.leave_type_id} | "
                f"total={total} carry={carry}"
            )

            if dry_run:
                (results["carried"] if carry > 0 else results["zeroed"]).append(
                    f"[DRY RUN] {tag}"
                )
                continue

            try:
                with transaction.atomic():
                    al_locked = AvailableLeave.objects.select_for_update().get(pk=al.pk)
                    al_locked.carryforward_days = float(carry)
                    al_locked.available_days = 0.0  # replenished by Cycle 1 credit shortly
                    al_locked._change_reason = f"Year-end carry-forward ({leave_year})"
                    al_locked.save()
                (results["carried"] if carry > 0 else results["zeroed"]).append(tag)
            except Exception as exc:
                logger.exception("Year-end carry-forward error for %s", al.employee_id)
                results["errors"].append(f"{al.employee_id} | {exc}")

    return results
