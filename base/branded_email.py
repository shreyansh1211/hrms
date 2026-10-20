"""
Infisetu-branded e-mail templates and sender.

* ``TEMPLATES`` holds every template (key -> subject, body). ``seed_email_templates``
  writes them to Settings -> Email -> Templates (``HorillaMailTemplate``) where
  they can be edited; ``send_branded`` always prefers the edited copy.
* Placeholders use ``{{ instance.xxx }}`` / ``{{ app_url }}`` so the same template
  works from system events (a plain dict is passed as ``instance``) and from the
  recruitment "send mail" screen (a model instance is passed).
* Mail is sent from a background thread; a mail failure is logged, never raised.
"""

import logging
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template

logger = logging.getLogger(__name__)

TEAL = "#017391"
NAVY = "#132238"
SKY = "#38BDF8"
SLATE = "#64748B"


def app_url():
    base = getattr(settings, "SITE_URL", None)
    if not base:
        origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or []
        base = origins[0] if origins else "http://localhost:8000"
    return base.rstrip("/")


def button(label, href):
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0 8px 0;">'
        f'<tr><td style="background:{TEAL};border-radius:4px;">'
        f'<a href="{href}" style="display:inline-block;padding:12px 26px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;font-weight:bold;color:#ffffff;text-decoration:none;">{label}</a>'
        f"</td></tr></table>"
    )


def details(rows):
    """Two-column key/value block. ``rows`` = [(label, value_html), ...]."""
    cells = "".join(
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;width:38%;'
        f'font-size:13px;color:{SLATE};">{k}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-size:14px;'
        f'color:{NAVY};">{v}</td></tr>'
        for k, v in rows
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:18px 0;border:1px solid #e2e8f0;border-radius:4px;">{cells}</table>'
    )


def notice(text_html):
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0;">'
        f'<tr><td style="border-left:4px solid {SKY};background:#f4fafc;padding:12px 16px;'
        f'font-size:14px;line-height:1.6;color:{NAVY};">{text_html}</td></tr></table>'
    )


def p(text):
    return f'<p style="margin:0 0 14px 0;font-size:15px;line-height:1.65;color:#1e293b;">{text}</p>'


def layout(heading, body_html):
    return f"""<div style="margin:0;padding:0;background:#eef2f6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f6;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:96%;background:#ffffff;border-radius:6px;overflow:hidden;border:1px solid #dbe3ec;">
<tr><td style="background:{TEAL};padding:22px 32px;">
<div style="font-family:Arial,Helvetica,sans-serif;font-size:22px;font-weight:bold;letter-spacing:4px;color:#ffffff;">INFISETU</div>
<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:3px;color:#cfe9f1;margin-top:2px;">TECHNOLOGIES</div>
</td></tr>
<tr><td style="height:3px;background:{SKY};font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:30px 32px 12px 32px;font-family:Arial,Helvetica,sans-serif;">
<h1 style="margin:0 0 18px 0;font-size:20px;line-height:1.3;color:{NAVY};font-weight:bold;">{heading}</h1>
{body_html}
</td></tr>
<tr><td style="padding:18px 32px 26px 32px;font-family:Arial,Helvetica,sans-serif;border-top:1px solid #e2e8f0;">
<p style="margin:0;font-size:12px;line-height:1.6;color:{SLATE};">Infisetu Technologies &middot; Infisetu MIS<br>
This is an automated message from the company management system. Please do not reply to this address; contact your reporting manager or HR for any questions.</p>
</td></tr>
</table></td></tr></table></div>"""


def _open(label="Open in Infisetu MIS", path=""):
    return button(label, "{{ app_url }}" + path)


# key -> (subject, heading, body)
_DEFS = {
    "Leave Request Submitted": (
        "Leave request from {{ instance.employee }}: {{ instance.start_date }} to {{ instance.end_date }}",
        "Leave request awaiting your approval",
        p("{{ instance.employee }} has applied for leave and the request is waiting for your decision.")
        + details([
            ("Employee", "{{ instance.employee }}"),
            ("Leave type", "{{ instance.leave_type }}"),
            ("From", "{{ instance.start_date }}"),
            ("To", "{{ instance.end_date }}"),
            ("Days", "{{ instance.days }}"),
            ("Reason", "{{ instance.reason }}"),
        ])
        + _open("Review request", "/leave/user-request-view/"),
    ),
    "Leave Approved": (
        "Your leave has been approved ({{ instance.start_date }} to {{ instance.end_date }})",
        "Your leave request is approved",
        p("Hello {{ instance.employee }},")
        + p("Your leave request has been approved. Please plan hand-over of any pending work before you leave.")
        + details([
            ("Leave type", "{{ instance.leave_type }}"),
            ("From", "{{ instance.start_date }}"),
            ("To", "{{ instance.end_date }}"),
            ("Days", "{{ instance.days }}"),
        ]),
    ),
    "Leave Rejected": (
        "Your leave request was not approved ({{ instance.start_date }} to {{ instance.end_date }})",
        "Your leave request was not approved",
        p("Hello {{ instance.employee }},")
        + p("Your leave request could not be approved.")
        + details([
            ("Leave type", "{{ instance.leave_type }}"),
            ("From", "{{ instance.start_date }}"),
            ("To", "{{ instance.end_date }}"),
            ("Reason given", "{{ instance.reject_reason }}"),
        ])
        + p("If you need to discuss this, please speak to your reporting manager."),
    ),
    "Short Notice Leave Request": (
        "Short-notice leave request: {{ instance.employee }}, {{ instance.start_date }} to {{ instance.end_date }}",
        "Short-notice leave request",
        p("Leave of more than three consecutive days must be applied for at least seven days in advance. "
          "This request falls inside that period, so it cannot be raised in Infisetu MIS and is being sent by e-mail for a decision.")
        + details([
            ("Employee", "{{ instance.employee }}"),
            ("From", "{{ instance.start_date }}"),
            ("To", "{{ instance.end_date }}"),
            ("Days", "{{ instance.days }}"),
            ("Reason", "{{ instance.reason }}"),
        ])
        + p("Use this template as the body of your e-mail to your reporting manager, with HR in copy."),
    ),
    "Attendance Intimation - Action Required": (
        "Action required: {{ instance.kind }} on {{ instance.date }}",
        "Attendance intimation needs your response",
        p("Hello {{ instance.employee }},")
        + p("{{ instance.summary }}")
        + details([
            ("Date", "{{ instance.date }}"),
            ("Your shift", "{{ instance.shift }}"),
            ("Recorded", "{{ instance.recorded }}"),
        ])
        + notice("Open the intimation in Infisetu MIS, add a comment (and proof, if you have it) and send it to your "
                 "reporting manager for approval. Items left open may be treated as unauthorised absence from the shift.")
        + _open("Respond to intimation", "/attendance/intimations/"),
    ),
    "Missed Sign-out Notice": (
        "You were signed out automatically on {{ instance.date }}",
        "You did not sign out on {{ instance.date }}",
        p("Hello {{ instance.employee }},")
        + p("You checked in on {{ instance.date }} and were still signed in {{ instance.hours }} hours later, "
            "so the system signed you out automatically at {{ instance.out_time }}.")
        + notice("This time may not match when you actually finished work. Open the intimation in Infisetu MIS, "
                 "enter your actual sign-out time with a comment, and send it to your reporting manager. "
                 "Once approved your attendance is corrected; no separate e-mail is needed.")
        + _open("Correct my sign-out", "/attendance/intimations/"),
    ),
    "Attendance Intimation - Submitted": (
        "Intimation from {{ instance.employee }} awaiting approval ({{ instance.date }})",
        "An attendance intimation needs your approval",
        p("{{ instance.employee }} has responded to an attendance intimation.")
        + details([
            ("Employee", "{{ instance.employee }}"),
            ("Type", "{{ instance.kind }}"),
            ("Date", "{{ instance.date }}"),
            ("Comment", "{{ instance.comment }}"),
            ("Actual sign-out", "{{ instance.requested_out }}"),
        ])
        + _open("Review intimation", "/attendance/intimations/"),
    ),
    "Attendance Intimation - Decision": (
        "Your attendance intimation was {{ instance.status }} ({{ instance.date }})",
        "Your intimation was {{ instance.status }}",
        p("Hello {{ instance.employee }},")
        + p("Your reporting manager has reviewed your intimation for {{ instance.date }}.")
        + details([
            ("Type", "{{ instance.kind }}"),
            ("Decision", "{{ instance.status }}"),
            ("Manager's note", "{{ instance.manager_comment }}"),
        ]),
    ),
    "Project Manager Assignment": (
        "You are a manager of project: {{ instance.project }}",
        "You have been made a project manager",
        p("You have been assigned as a manager of the project <strong>{{ instance.project }}</strong>.")
        + details([
            ("Project", "{{ instance.project }}"),
            ("Start", "{{ instance.start_date }}"),
            ("End", "{{ instance.end_date }}"),
        ])
        + p("{{ instance.description }}")
        + _open("Open the project", "{{ instance.path }}"),
    ),
    "Project Team Assignment": (
        "You are on project: {{ instance.project }}",
        "You have been added to a project team",
        p("You have been added to <strong>{{ instance.project }}</strong> as <strong>{{ instance.role }}</strong>.")
        + details([
            ("Project", "{{ instance.project }}"),
            ("Your role", "{{ instance.role }}"),
            ("Start", "{{ instance.start_date }}"),
            ("End", "{{ instance.end_date }}"),
        ])
        + p("{{ instance.description }}")
        + _open("Open the project", "{{ instance.path }}"),
    ),
    "Task Assignment": (
        "New task assigned: {{ instance.task }}",
        "A task has been assigned to you",
        p("You have been assigned as {{ instance.role }} on a task.")
        + details([
            ("Task", "{{ instance.task }}"),
            ("Project", "{{ instance.project }}"),
            ("Type", "{{ instance.task_type }}"),
            ("Priority", "{{ instance.priority }}"),
            ("Due", "{{ instance.due }}"),
        ])
        + p("{{ instance.description }}")
        + _open("Open the project", "{{ instance.path }}"),
    ),
    "Payslip Available": (
        "Your payslip for {{ instance.period }} is available",
        "Your payslip is ready",
        p("Hello {{ instance.employee }},")
        + p("Your payslip for <strong>{{ instance.period }}</strong> has been processed and is available in Infisetu MIS.")
        + _open("View payslip", "/payroll/"),
    ),
    "Asset Allocated": (
        "Asset allocated to you: {{ instance.asset }}",
        "A company asset has been allocated to you",
        p("Hello {{ instance.employee }},")
        + p("The following asset has been allocated to you. You are responsible for its care and for returning it "
            "in good condition when you leave or when it is replaced.")
        + details([
            ("Asset", "{{ instance.asset }}"),
            ("Asset ID", "{{ instance.asset_id }}"),
            ("Allocated on", "{{ instance.date }}"),
        ]),
    ),
    # --- recruitment: used from the Recruitment / Onboarding "send mail" screens,
    # where `instance` is the Candidate record.
    "Onboarding Invitation": (
        "Welcome to Infisetu Technologies - complete your joining details",
        "Welcome to Infisetu Technologies",
        p("Dear {{ instance.name }},")
        + p("We are pleased to confirm your selection for the position of <strong>{{ instance.job_position_id }}</strong>. "
            "To complete your joining formalities, please use the secure link in this e-mail to create your account and fill in "
            "your personal and bank details.")
        + p("Please keep scanned copies of your identity, address and education documents ready.")
        + p("We look forward to having you on the team."),
    ),
    "Interview Scheduled": (
        "Interview schedule - {{ instance.job_position_id }} at Infisetu Technologies",
        "Your interview has been scheduled",
        p("Dear {{ instance.name }},")
        + p("Thank you for your interest in the <strong>{{ instance.job_position_id }}</strong> position at Infisetu Technologies. "
            "We would like to invite you for an interview. The date, time and mode are given below.")
        + details([
            ("Position", "{{ instance.job_position_id }}"),
            ("Date and time", "{{ instance.schedule_date }}"),
        ])
        + p("Please confirm your availability by replying to the HR team. Carry a copy of your resume and a valid photo ID."),
    ),
    "Offer of Employment": (
        "Offer of employment - {{ instance.job_position_id }}, Infisetu Technologies",
        "Offer of employment",
        p("Dear {{ instance.name }},")
        + p("Further to your interviews, we are pleased to offer you the position of "
            "<strong>{{ instance.job_position_id }}</strong> at Infisetu Technologies.")
        + details([
            ("Position", "{{ instance.job_position_id }}"),
            ("Joining date", "{{ instance.joining_date }}"),
        ])
        + p("The detailed offer letter with compensation and terms is attached. Please sign and return it to confirm your acceptance.")
        + p("We are glad to welcome you to the team."),
    ),
    "Application Update": (
        "Your application to Infisetu Technologies",
        "Update on your application",
        p("Dear {{ instance.name }},")
        + p("Thank you for the time you invested in applying for the <strong>{{ instance.job_position_id }}</strong> position "
            "at Infisetu Technologies and for speaking with our team.")
        + p("After careful consideration we have decided not to take your application forward at this time. "
            "This is not a reflection of your potential, and we will keep your profile on record for suitable openings in the future.")
        + p("We wish you every success in your career."),
    ),
}


def _build_templates():
    out = {}
    for title, (subject, heading, body) in _DEFS.items():
        out[title] = {"subject": subject, "body": layout(heading, body)}
    return out


TEMPLATES = _build_templates()


def render_branded(key, instance=None, extra=None):
    """Return (subject, html) for template ``key``, preferring the edited DB copy."""
    from base.methods import sanitize_mail_template_body
    from base.models import HorillaMailTemplate

    subject_src = TEMPLATES[key]["subject"]
    body_src = TEMPLATES[key]["body"]
    stored = HorillaMailTemplate.objects.filter(title=key).first()
    if stored and stored.body:
        body_src = stored.body
    context = Context({"instance": instance or {}, "app_url": app_url(), **(extra or {})})
    subject = Template(sanitize_mail_template_body(subject_src)).render(context)
    html = Template(sanitize_mail_template_body(body_src)).render(context)
    return " ".join(subject.split()), html


def _send(subject, html, to, cc):
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
        msg = EmailMultiAlternatives(subject, text, None, to, cc=cc or None)
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception:
        logger.exception("Branded e-mail '%s' to %s failed", subject, to)


def send_branded(key, to, instance=None, cc=None, extra=None, background=True):
    """Render and send template ``key``. ``to`` is an address or list."""
    to = [to] if isinstance(to, str) else [t for t in to if t]
    if not to:
        return False
    try:
        subject, html = render_branded(key, instance, extra)
    except Exception:
        logger.exception("Could not render e-mail template '%s'", key)
        return False
    if background and not getattr(settings, "BRANDED_EMAIL_SYNC", False):
        threading.Thread(target=_send, args=(subject, html, to, cc), daemon=True).start()
    else:
        _send(subject, html, to, cc)
    return True
