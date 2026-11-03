"""
CBV views for HR leave cycle policy management and credit log.
"""

from typing import Any

from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _

from base.decorators import manager_can_enter
from horilla_views.cbv_methods import login_required
from horilla_views.generic.cbv.views import (
    HorillaFormView,
    HorillaListView,
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

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("leave-cycle-policy-list")

    def get_queryset(self, queryset=None, filtered=False):
        # Must call super() so HorillaListView sets self.queryset and
        # self._saved_filters — without this get_context_data crashes.
        qs = super().get_queryset(queryset=queryset, filtered=filtered)
        return qs.select_related("leave_type_id", "company_id")


@method_decorator(login_required, name="dispatch")
@method_decorator(manager_can_enter("leave.change_leavetype"), name="dispatch")
class LeaveCyclePolicyFormView(HorillaFormView):
    model = LeaveCyclePolicy
    form_class = LeaveCyclePolicyForm
    new_display_title = _("Add Leave Cycle Policy")
    edit_display_title = _("Edit Leave Cycle Policy")
    http_method_names = ["get", "post"]


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
        # Must call super() so HorillaListView sets self._saved_filters.
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
