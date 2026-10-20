"""
Project team (who works on a project, in which role) and the "my project
hours" panel of the employee dashboard.
"""

from collections import defaultdict
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from employee.methods.duration_methods import format_time, strtime_seconds
from employee.models import Employee
from project.methods import employees_for_project
from project.models import Project, ProjectMember, TimeSheet


def _employee(request):
    return getattr(request.user, "employee_get", None)


def _can_manage(request, project):
    user = request.user
    if user.is_superuser or user.has_perm("project.change_project"):
        return True
    employee = _employee(request)
    return employee is not None and project.managers.filter(pk=employee.pk).exists()


def _can_view(request, project):
    if _can_manage(request, project) or request.user.has_perm("project.view_project"):
        return True
    employee = _employee(request)
    if employee is None:
        return False
    return (
        project.project_team.filter(employee_id=employee).exists()
        or project.task_set.filter(task_members=employee).exists()
        or project.task_set.filter(task_managers=employee).exists()
    )


def _render_team(request, project, error=None):
    team = project.project_team.select_related("employee_id")
    taken = team.values_list("employee_id", flat=True)
    return render(
        request,
        "cbv/projects/project_team.html",
        {
            "project": project,
            "team": team,
            "roles": ProjectMember.ROLES,
            "candidates": employees_for_project(project).exclude(pk__in=taken),
            "can_manage": _can_manage(request, project),
            "error": error,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_team(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _can_view(request, project):
        return HttpResponseForbidden("You do not have access to this project.")
    error = None
    if request.method == "POST":
        if not _can_manage(request, project):
            return HttpResponseForbidden("Only project managers can edit the team.")
        role = request.POST.get("role")
        employee = employees_for_project(project).filter(
            pk=request.POST.get("employee") or 0
        ).first()
        if employee is None or role not in dict(ProjectMember.ROLES):
            error = "Choose an employee and a role."
        else:
            ProjectMember.objects.update_or_create(
                project=project, employee_id=employee, defaults={"role": role}
            )
    return _render_team(request, project, error)


@login_required
@require_http_methods(["POST"])
def project_team_remove(request, member_id):
    member = get_object_or_404(ProjectMember, pk=member_id)
    if not _can_manage(request, member.project):
        return HttpResponseForbidden("Only project managers can edit the team.")
    project = member.project
    member.delete()
    return _render_team(request, project)


@login_required
def my_project_hours(request):
    """GET /project/my-hours/?from_date=&to_date= -- logged hours per project."""
    employee = _employee(request)
    if employee is None:
        return JsonResponse({"projects": [], "total": "00:00"})
    today = date.today()
    try:
        start = date.fromisoformat(request.GET.get("from_date", ""))
    except ValueError:
        start = today.replace(day=1)
    try:
        end = date.fromisoformat(request.GET.get("to_date", ""))
    except ValueError:
        end = today

    seconds = defaultdict(int)
    names = {}
    for sheet in TimeSheet.objects.filter(
        employee_id=employee, date__gte=start, date__lte=end, project_id__isnull=False
    ).select_related("project_id"):
        try:
            seconds[sheet.project_id_id] += strtime_seconds(sheet.time_spent or "0:0")
        except (ValueError, AttributeError):
            continue
        names[sheet.project_id_id] = sheet.project_id.title

    roles = dict(
        ProjectMember.objects.filter(employee_id=employee).values_list(
            "project_id", "role"
        )
    )
    role_labels = dict(ProjectMember.ROLES)
    projects = [
        {
            "id": pid,
            "title": names[pid],
            "hours": format_time(secs),
            "role": role_labels.get(roles.get(pid), ""),
        }
        for pid, secs in sorted(seconds.items(), key=lambda kv: -kv[1])
    ]
    return JsonResponse(
        {"projects": projects, "total": format_time(sum(seconds.values()))}
    )
