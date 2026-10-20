"""
Send a branded e-mail whenever someone is assigned to a project or task.
The wording lives in Settings -> Email -> Templates (see base.branded_email).
"""

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from django.urls import reverse

from base.branded_email import send_branded
from employee.models import Employee
from project.models import Project, ProjectMember, Task


def _fmt(day):
    return day.strftime("%d %b %Y") if day else "Not set"


def _project_data(project):
    return {
        "project": project.title,
        "start_date": _fmt(project.start_date),
        "end_date": _fmt(project.end_date),
        "description": project.description,
        "path": reverse("task-view", kwargs={"project_id": project.pk}),
    }


@receiver(m2m_changed, sender=Project.managers.through)
def project_manager_added(sender, instance, action, reverse, pk_set, **kwargs):
    if action != "post_add" or reverse:
        return
    for employee in Employee.objects.filter(pk__in=pk_set):
        send_branded(
            "Project Manager Assignment",
            employee.get_email(),
            _project_data(instance),
        )


@receiver(post_save, sender=ProjectMember)
def project_member_added(sender, instance, created, **kwargs):
    if not created:
        return
    data = _project_data(instance.project)
    data["role"] = instance.get_role_display()
    send_branded("Project Team Assignment", instance.employee_id.get_email(), data)


def _task_assigned(instance, action, reverse_rel, pk_set, role_label):
    if action != "post_add" or reverse_rel or not instance.project:
        return
    data = {
        "task": instance.title,
        "project": instance.project.title,
        "task_type": instance.get_task_type_display(),
        "priority": instance.get_priority_display(),
        "due": _fmt(instance.end_date),
        "description": instance.description,
        "role": role_label,
        "path": reverse("task-view", kwargs={"project_id": instance.project.pk}),
    }
    for employee in Employee.objects.filter(pk__in=pk_set):
        send_branded("Task Assignment", employee.get_email(), data)


@receiver(m2m_changed, sender=Task.task_members.through)
def task_member_added(sender, instance, action, reverse, pk_set, **kwargs):
    _task_assigned(instance, action, reverse, pk_set, "a member")


@receiver(m2m_changed, sender=Task.task_managers.through)
def task_manager_added(sender, instance, action, reverse, pk_set, **kwargs):
    _task_assigned(instance, action, reverse, pk_set, "a manager")
