"""
Assignment e-mails for the project app.

Mail is sent from a background thread so a slow or misconfigured SMTP server
never delays the request that triggered it; failures are logged, not raised.
"""

import logging
import threading

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


def _base_url():
    base = getattr(settings, "SITE_URL", None)
    if not base:
        origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or []
        base = origins[0] if origins else "http://localhost:8000"
    return base.rstrip("/")


def project_link(project):
    return _base_url() + reverse("task-view", kwargs={"project_id": project.pk})


def _send(subject, body, recipient):
    try:
        send_mail(subject, body, None, [recipient])
    except Exception:
        logger.exception("Project assignment e-mail to %s failed", recipient)


def notify_assignee(employee, subject, body):
    """E-mail one employee in the background; silently skip if no address."""
    try:
        address = employee.get_email()
    except Exception:
        address = None
    if not address:
        return
    full_body = f"Hi {employee.get_full_name()},\n\n{body}\n\nInfisetu MIS"
    threading.Thread(
        target=_send,
        args=(f"[Infisetu MIS] {subject}", full_body, address),
        daemon=True,
    ).start()
