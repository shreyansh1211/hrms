"""
CBV views for HR leave cycle policy management and credit log.
"""

from typing import Any

from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _

from django.contrib.auth.decorators import login_required as django_login_required

from base.decorators import manager_can_enter
from horilla_views.cbv_methods import login_required
from horilla_views.generic.cbv.views import (
    HorillaFormView,
    HorillaListView,
    HorillaNavView,
    TemplateView,
)
from leave.forms import LeaveCyclePolicyForm
from leave.models import LeaveCycleLog, LeaveCyclePolicy


@method_decorator(login_required, name="dispatch")
@method_decorator(manager_can_enter("leave.view_leavetype"), name="dispatch")
class LeaveCyclePolicyPage(TemplateView):
    template_name = "leave/cycle_policy_home.html"


@method_decorator(login_required, name="dispatch")
@method_decorator(manager_can_enter("leave.view_leavetype"), name="dispatch")
class LeaveCyclePolicyList(HorillaListView):
    model = LeaveCyclePolicy
    columns = [
        (_("Leave Type"), "leave_type_id"),
        (_("Cycle"), "get_cycle_number_display"),
        (_("Credit Month"), "get_credit_month_display"),
        (_("Credit Day"), "credit_day"),
        (_("Days"), "days_to_credit"),
        (_("Carry Forward %"), "carryforward_percent"),
        (_("Active"), "is_active"),
    ]
    search_url = ""
    action_method = "actions_col"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("leave-cycle-policy-list")

    def get_queryset(self, queryset=None, filtered=False):
        qs = super().get_queryset(queryset=queryset, filtered=filtered)
        return qs.select_related("leave_type_id", "company_id")


@method_decorator(login_required, name="dispatch")
@method_decorator(manager_can_enter("leave.view_leavetype"), name="dispatch")
class LeaveCyclePolicyNav(HorillaNavView):
    """Nav bar for the cycle policy page — renders the title, search, and Add Policy button."""

    nav_title = _("Leave Cycle Policies")
    search_url = ""
    search_swap_target = "#cyclePolicyList"
    template_name = "generic/inline_nav.html"
    apply_first_filter = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("leave-cycle-policy-list")
        if self.request and self.request.user.has_perm("leave.change_leavetype"):
            self.create_attrs = (
                'onclick="event.stopPropagation();"'
                ' data-toggle="oh-modal-toggle"'
                ' data-target="#objectCreateModal"'
                f' hx-get="{reverse("leave-cycle-policy-form")}"'
                ' hx-target="#objectCreateModalTarget"'
            )


@method_decorator(login_required, name="dispatch")
@method_decorator(manager_can_enter("leave.change_leavetype"), name="dispatch")
class LeaveCyclePolicyFormView(HorillaFormView):
    model = LeaveCyclePolicy
    form_class = LeaveCyclePolicyForm
    new_display_title = _("Add Leave Cycle Policy")
    edit_display_title = _("Edit Leave Cycle Policy")
    http_method_names = ["get", "post"]

    def form_valid(self, form):
        if form.is_valid():
            form.save()
            messages.success(
                self.request, _("Leave cycle policy saved successfully.")
            )
        return self.HttpResponse()


@method_decorator(login_required, name="dispatch")
@method_decorator(manager_can_enter("leave.view_leavetype"), name="dispatch")
class LeaveCycleLogList(HorillaListView):
    model = LeaveCycleLog
    columns = [
        (_("Employee"), "employee_id", "employee_id__get_avatar"),
        (_("Leave Type"), "leave_type_id"),
        (_("Year"), "leave_year"),
        (_("Cycle"), "cycle_number"),
        (_("Days"), "days_credited"),
        (_("Date"), "credited_on"),
        (_("Source"), "source"),
    ]
    search_url = ""
    bulk_select_option = False
    option_method = None
    action_method = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("leave-cycle-log-list")

    def get_queryset(self, queryset=None, filtered=False):
        qs = super().get_queryset(queryset=queryset, filtered=filtered)
        qs = qs.select_related("employee_id", "leave_type_id")
        year = self.request.GET.get("year")
        cycle = self.request.GET.get("cycle")
        emp = self.request.GET.get("employee")
        if year:
            qs = qs.filter(leave_year=year)
        if cycle:
            qs = qs.filter(cycle_number=cycle)
        if emp:
            qs = qs.filter(employee_id=emp)
        return qs


@django_login_required
def leave_cycle_policy_delete(request, pk):
    """Delete a LeaveCyclePolicy and return the refreshed list."""
    if not request.user.has_perm("leave.delete_leavetype"):
        messages.error(request, _("You do not have permission to delete policies."))
        return LeaveCyclePolicyList.as_view()(request)
    try:
        LeaveCyclePolicy.objects.get(pk=pk).delete()
        messages.success(request, _("Leave cycle policy deleted successfully."))
    except LeaveCyclePolicy.DoesNotExist:
        messages.error(request, _("Policy not found."))
    return LeaveCyclePolicyList.as_view()(request)
