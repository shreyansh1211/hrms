from django.db import models

from employee.models import Employee


class ActiveTimeDay(models.Model):
    """
    Daily desk-activity totals for one employee, copied from the Infi Time
    Manager server (totals only: no URLs, window titles or screenshots ever
    reach the HRMS). The detailed view lives in the tracker's own console.
    """

    employee_id = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="active_time_days"
    )
    date = models.DateField()
    active_seconds = models.PositiveIntegerField(default=0)
    tracked_seconds = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    agent_status = models.CharField(max_length=30, blank=True)
    tracker_employee_id = models.PositiveIntegerField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee_id", "date")
        indexes = [models.Index(fields=["date"])]
        ordering = ["-date"]
        verbose_name = "Active time (day)"
        verbose_name_plural = "Active time (days)"

    def __str__(self):
        return f"{self.employee_id} {self.date}: {self.active_seconds}s"
