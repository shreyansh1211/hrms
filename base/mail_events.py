"""
System events that send a branded e-mail (see base.branded_email for the
templates, editable under Settings -> Email -> Templates):

* leave request submitted      -> reporting manager
* leave approved / rejected    -> employee
* payslip marked paid          -> employee
* asset allocated              -> employee

Project assignments and attendance intimations are sent from their own apps.
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from base.branded_email import send_branded

logger = logging.getLogger(__name__)


def _day(value):
    return value.strftime("%d %b %Y") if value else "-"


# --- leave -------------------------------------------------------------------------------
@receiver(pre_save, sender="leave.LeaveRequest")
def _remember_leave_status(sender, instance, **kwargs):
    instance._previous_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk
        else None
    )


def _leave_data(leave):
    return {
        "employee": leave.employee_id.get_full_name(),
        "leave_type": str(leave.leave_type_id),
        "start_date": _day(leave.start_date),
        "end_date": _day(leave.end_date or leave.start_date),
        "days": f"{leave.requested_days:g}" if leave.requested_days is not None else "-",
        "reason": leave.description or "-",
        "reject_reason": leave.reject_reason or "-",
    }


@receiver(post_save, sender="leave.LeaveRequest")
def _leave_mail(sender, instance, created, **kwargs):
    try:
        data = _leave_data(instance)
        if created and instance.status == "requested":
            manager = instance.employee_id.employee_work_info.reporting_manager_id
            if manager:
                send_branded("Leave Request Submitted", manager.get_email(), data)
            return
        previous = getattr(instance, "_previous_status", None)
        if previous != instance.status and instance.status in ("approved", "rejected"):
            key = "Leave Approved" if instance.status == "approved" else "Leave Rejected"
            send_branded(key, instance.employee_id.get_email(), data)
    except Exception:
        logger.exception("Leave e-mail failed")


# --- payroll -----------------------------------------------------------------------------
@receiver(pre_save, sender="payroll.Payslip")
def _remember_payslip_status(sender, instance, **kwargs):
    instance._previous_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk
        else None
    )


@receiver(post_save, sender="payroll.Payslip")
def _payslip_mail(sender, instance, created, **kwargs):
    try:
        if instance.status != "paid" or getattr(instance, "_previous_status", None) == "paid":
            return
        period = f"{instance.start_date:%d %b %Y} - {instance.end_date:%d %b %Y}"
        send_branded(
            "Payslip Available",
            instance.employee_id.get_email(),
            {"employee": instance.employee_id.get_full_name(), "period": period},
        )
    except Exception:
        logger.exception("Payslip e-mail failed")


# --- assets ------------------------------------------------------------------------------
@receiver(post_save, sender="asset.AssetAssignment")
def _asset_mail(sender, instance, created, **kwargs):
    try:
        if not created:
            return
        employee = instance.assigned_to_employee_id
        send_branded(
            "Asset Allocated",
            employee.get_email(),
            {
                "employee": employee.get_full_name(),
                "asset": str(instance.asset_id),
                "asset_id": getattr(instance.asset_id, "asset_tracking_id", "-"),
                "date": _day(instance.assigned_date) if instance.assigned_date else _day(None),
            },
        )
    except Exception:
        logger.exception("Asset e-mail failed")
