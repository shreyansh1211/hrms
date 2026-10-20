"""
Attendance -> Intimations: employees answer late / early / missed-sign-out
notices, reporting managers approve or reject them.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from attendance import intimations
from attendance.models import AttendanceIntimation


def _me(request):
    return getattr(request.user, "employee_get", None)


def _reviewable(request):
    """Submitted intimations this user may approve."""
    user = request.user
    qs = AttendanceIntimation.objects.filter(status="submitted").select_related(
        "employee_id", "attendance_id"
    )
    if user.is_superuser or user.has_perm("attendance.change_attendance"):
        return qs
    me = _me(request)
    if me is None:
        return qs.none()
    return qs.filter(employee_id__employee_work_info__reporting_manager_id=me)


@login_required
def intimations_page(request):
    me = _me(request)
    mine = (
        AttendanceIntimation.objects.filter(employee_id=me).select_related(
            "attendance_id"
        )
        if me
        else AttendanceIntimation.objects.none()
    )
    return render(
        request,
        "attendance/intimations.html",
        {
            "open_items": mine.filter(Q(status="open") | Q(status="rejected")),
            "waiting": mine.filter(status="submitted"),
            "history": mine.filter(status="approved")[:20],
            "to_review": _reviewable(request),
        },
    )


@login_required
def intimation_count(request):
    me = _me(request)
    count = (
        AttendanceIntimation.objects.filter(
            employee_id=me, status__in=["open", "rejected"]
        ).count()
        if me
        else 0
    )
    return JsonResponse(
        {"open": count, "to_review": _reviewable(request).count()}
    )


@login_required
@require_http_methods(["POST"])
def intimation_submit(request, pk):
    me = _me(request)
    item = get_object_or_404(AttendanceIntimation, pk=pk)
    if me is None or item.employee_id_id != me.pk:
        return HttpResponseForbidden("This intimation belongs to another employee.")
    if item.status not in ("open", "rejected"):
        messages.info(request, "This intimation has already been sent.")
        return redirect("attendance-intimations")
    actual_out = None
    raw = (request.POST.get("actual_out") or "").strip()
    if raw:
        try:
            actual_out = datetime.datetime.strptime(raw, "%H:%M").time()
        except ValueError:
            messages.error(request, "Enter the sign-out time as HH:MM.")
            return redirect("attendance-intimations")
    try:
        intimations.submit(
            item,
            request.POST.get("comment"),
            request.FILES.get("proof"),
            actual_out,
        )
        messages.success(request, "Sent to your reporting manager for approval.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("attendance-intimations")


@login_required
@require_http_methods(["POST"])
def intimation_decide(request, pk):
    item = get_object_or_404(AttendanceIntimation, pk=pk)
    if not intimations.can_review(request.user, item):
        return HttpResponseForbidden("Only the reporting manager can decide this.")
    if item.status != "submitted":
        messages.info(request, "This intimation has already been decided.")
        return redirect("attendance-intimations")
    approve = request.POST.get("decision") == "approve"
    intimations.decide(item, approve, request.user, request.POST.get("manager_comment"))
    messages.success(request, "Approved." if approve else "Rejected.")
    return redirect("attendance-intimations")
