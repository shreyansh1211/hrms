import secrets

from django.db import models
from django.utils import timezone

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


class AgentToken(models.Model):
    """30-day auth token issued to a desktop agent when the employee logs in."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="agent_tokens"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    device_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent token"

    def __str__(self):
        return f"{self.employee} — {self.device_name or 'unknown device'}"

    @classmethod
    def create_for(cls, employee, device_name=""):
        from datetime import timedelta
        token = secrets.token_hex(32)
        expires = timezone.now() + timedelta(days=30)
        return cls.objects.create(
            employee=employee,
            token=token,
            device_name=device_name,
            expires_at=expires,
        )

    def is_valid(self):
        return self.is_active and self.expires_at > timezone.now()

    def touch(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at"])


class ActivitySegment(models.Model):
    """
    A short (≤120 s) window of tracked time sent by the desktop agent.
    active=True means real keyboard/mouse input was seen in this window.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="activity_segments"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    active = models.BooleanField(default=False)
    app_name = models.CharField(max_length=200, blank=True)
    window_title = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=1000, blank=True)
    keys = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    moves = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["employee", "start"]),
            models.Index(fields=["start"]),
        ]
        ordering = ["-start"]
        verbose_name = "Activity segment"

    def duration_seconds(self):
        return max(0, int((self.end - self.start).total_seconds()))

    def __str__(self):
        return f"{self.employee} {self.start:%Y-%m-%d %H:%M} {'active' if self.active else 'idle'}"


class AppUsageLog(models.Model):
    """Aggregated time an employee spent in each application per day."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="app_usage_logs"
    )
    date = models.DateField()
    app_name = models.CharField(max_length=200)
    seconds = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("employee", "date", "app_name")
        indexes = [models.Index(fields=["employee", "date"])]
        ordering = ["-date", "-seconds"]
        verbose_name = "App usage log"

    def __str__(self):
        return f"{self.employee} {self.date} — {self.app_name}: {self.seconds}s"


class BrowserTabLog(models.Model):
    """Time an employee spent on each browser domain/URL per day."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="browser_tab_logs"
    )
    date = models.DateField()
    url = models.CharField(max_length=1000)
    domain = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=500, blank=True)
    seconds = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["employee", "date"])]
        ordering = ["-date", "-seconds"]
        verbose_name = "Browser tab log"

    def __str__(self):
        return f"{self.employee} {self.date} — {self.domain or self.url}: {self.seconds}s"


class EmployeeScreenshot(models.Model):
    """Periodic screenshot captured by the desktop agent."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="screenshots"
    )
    captured_at = models.DateTimeField()
    image = models.ImageField(upload_to="tracker/screenshots/%Y/%m/%d/")
    active_at_capture = models.BooleanField(default=True)
    app_name = models.CharField(max_length=200, blank=True)
    window_title = models.CharField(max_length=500, blank=True)

    class Meta:
        indexes = [models.Index(fields=["employee", "captured_at"])]
        ordering = ["-captured_at"]
        verbose_name = "Screenshot"

    def __str__(self):
        return f"{self.employee} screenshot @ {self.captured_at:%Y-%m-%d %H:%M:%S}"
