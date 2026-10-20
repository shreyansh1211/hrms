"""
Task comment endpoints (HTMX fragments shown inside the task detail modal).
"""

from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from horilla.decorators import login_required
from project.models import Task, TaskComment


def _can_access(request, task):
    employee = getattr(request.user, "employee_get", None)
    user = request.user
    if user.is_superuser or user.has_perm("project.view_task"):
        return True
    if employee is None:
        return False
    return (
        task.project.managers.filter(pk=employee.pk).exists()
        or task.task_managers.filter(pk=employee.pk).exists()
        or task.task_members.filter(pk=employee.pk).exists()
    )


def _render(request, task):
    return render(
        request,
        "cbv/tasks/task_comments.html",
        {
            "task": task,
            "comments": task.comments.select_related("employee_id"),
            "current_employee": getattr(request.user, "employee_get", None),
            "is_admin": request.user.is_superuser
            or request.user.has_perm("project.delete_task"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_comments(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    if not _can_access(request, task):
        return HttpResponseForbidden("You do not have access to this task.")
    if request.method == "POST":
        text = (request.POST.get("comment") or "").strip()
        employee = getattr(request.user, "employee_get", None)
        if text and employee is not None:
            TaskComment.objects.create(
                task=task, employee_id=employee, comment=text[:5000]
            )
    return _render(request, task)


@login_required
@require_http_methods(["POST"])
def task_comment_delete(request, comment_id):
    comment = get_object_or_404(TaskComment, pk=comment_id)
    task = comment.task
    employee = getattr(request.user, "employee_get", None)
    is_author = employee is not None and comment.employee_id_id == employee.pk
    if not (
        is_author
        or request.user.is_superuser
        or request.user.has_perm("project.delete_task")
    ):
        return HttpResponseForbidden("You cannot delete this comment.")
    comment.delete()
    return _render(request, task)
