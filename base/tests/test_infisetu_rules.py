"""
Infisetu business rules: 30-minute grace + intimations, missed sign-out
correction from inside the HRMS, the leave notice rule and branded e-mails.
"""

import datetime
from io import StringIO
from types import SimpleNamespace

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from attendance import intimations
from attendance.models import Attendance, AttendanceActivity, AttendanceIntimation
from base.branded_email import TEMPLATES, render_branded
from base.models import EmployeeShift, EmployeeShiftDay
from horilla import horilla_middlewares
from horilla.testkit.factories import make_company, make_employee, make_user
from leave.models import AvailableLeave, LeaveRequest, LeaveType

SYNC_MAIL = {
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "BRANDED_EMAIL_SYNC": True,
}


class RulesBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_infisetu_setup", stdout=StringIO())
        company = make_company("InfiSetu Technologies")
        manager = make_employee(
            company=company, email="manager@example.com", first_name="Maya", last_name="Manager"
        )
        cls.shift = EmployeeShift.objects.get(employee_shift="Morning (10 AM - 7 PM)")
        cls.employee = make_employee(
            company=company, email="staff@example.com", first_name="Sam", last_name="Staff",
            shift=cls.shift,
        )
        wi = cls.employee.employee_work_info
        wi.reporting_manager_id = manager
        wi.save()
        cls.manager = manager
        cls.company = company

    def attendance(self, day, clock_in="10:00:00", clock_out=None):
        weekday = EmployeeShiftDay.objects.get(day=day.strftime("%A").lower())
        att = Attendance.objects.create(
            employee_id=self.employee, shift_id=self.shift, attendance_date=day,
            attendance_day=weekday, attendance_clock_in=clock_in,
            attendance_clock_in_date=day, minimum_hour="08:15",
        )
        AttendanceActivity.objects.create(
            employee_id=self.employee, attendance_date=day, clock_in_date=day,
            clock_in=clock_in, in_datetime=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time.fromisoformat(clock_in))),
        )
        if clock_out:
            att.attendance_clock_out = clock_out
            att.attendance_clock_out_date = day
            att.save()
        return att


@override_settings(**SYNC_MAIL)
class IntimationTests(RulesBase):
    def test_grace_period_boundaries(self):
        day = datetime.date(2026, 10, 14)  # Wednesday, shift 10:00-19:00
        on_time = self.attendance(day, "10:30:00", "18:30:00")  # exactly 30 min each way
        self.assertIsNone(intimations.check_late_in(on_time))
        self.assertIsNone(intimations.check_early_out(on_time))

    def test_late_in_and_early_out_flow(self):
        day = datetime.date(2026, 10, 15)
        att = self.attendance(day, "10:31:00", "18:29:00")
        late = intimations.check_late_in(att)
        early = intimations.check_early_out(att)
        self.assertEqual((late.kind, early.kind), ("late_in", "early_out"))
        self.assertIn("31 minutes", late.detail)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["staff@example.com"])

        with self.assertRaises(ValueError):
            intimations.submit(late, "")  # comment is mandatory
        intimations.submit(late, "Metro delay on the Blue line")
        self.assertEqual(late.status, "submitted")
        self.assertEqual(mail.outbox[-1].to, ["manager@example.com"])

        intimations.decide(late, True, make_user("boss", is_superuser=True), "Fine")
        self.assertEqual(late.status, "approved")
        self.assertEqual(mail.outbox[-1].to, ["staff@example.com"])
        self.assertIn("approved", mail.outbox[-1].subject)

    def test_missed_sign_out_is_visible_and_correctable(self):
        from attendance.scheduler import auto_sign_out_missed

        first_in = timezone.localtime() - datetime.timedelta(hours=15)
        day = first_in.date()
        att = self.attendance(day, first_in.strftime("%H:%M:00"))
        AttendanceActivity.objects.filter(employee_id=self.employee).update(
            in_datetime=first_in
        )
        auto_sign_out_missed()
        item = AttendanceIntimation.objects.get(kind="missed_sign_out")
        self.assertEqual(item.status, "open")
        self.assertTrue(any("signed out automatically" in m.subject for m in mail.outbox))

        # Employee says they really left 8h30m after check-in.
        actual = (first_in + datetime.timedelta(hours=8, minutes=30)).time().replace(
            second=0, microsecond=0
        )
        intimations.submit(item, "Forgot to sign out after the client call", None, actual)
        self.assertEqual(item.status, "submitted")
        intimations.decide(item, True, make_user("hr", is_superuser=True))
        att.refresh_from_db()
        self.assertEqual(att.attendance_worked_hour, "08:30")
        self.assertEqual(att.attendance_clock_out.strftime("%H:%M"), actual.strftime("%H:%M"))

    def test_actual_signout_cannot_exceed_12_hours(self):
        first_in = timezone.localtime() - datetime.timedelta(hours=15)
        att = self.attendance(first_in.date(), first_in.strftime("%H:%M:00"))
        item = AttendanceIntimation.objects.create(
            employee_id=self.employee, attendance_id=att, kind="missed_sign_out"
        )
        too_late = (first_in + datetime.timedelta(hours=13)).time()
        with self.assertRaises(ValueError):
            intimations.submit(item, "x", None, too_late)


class LeaveNoticeRuleTests(RulesBase):
    def setUp(self):
        self.leave_type = LeaveType.objects.get(name="Casual Leave")
        AvailableLeave.objects.create(
            employee_id=self.employee, leave_type_id=self.leave_type, available_days=10
        )
        user = self.employee.employee_user_id
        horilla_middlewares._thread_locals.request = SimpleNamespace(user=user, GET={}, session={})

    def tearDown(self):
        horilla_middlewares._thread_locals.request = None

    def request(self, start_in_days, length):
        start = datetime.date.today() + datetime.timedelta(days=start_in_days)
        return LeaveRequest(
            employee_id=self.employee, leave_type_id=self.leave_type,
            start_date=start, end_date=start + datetime.timedelta(days=length - 1),
            description="Family function",
        )

    def test_long_leave_inside_a_week_is_blocked(self):
        with self.assertRaises(ValidationError) as ctx:
            self.request(3, 4).clean()
        text = str(ctx.exception)
        self.assertIn("cannot be raised in Infisetu MIS", text)
        self.assertIn("manager@example.com", text)

    def test_exactly_three_days_is_allowed_at_short_notice(self):
        self.request(1, 3).clean()

    def test_long_leave_with_a_week_notice_is_allowed(self):
        self.request(7, 5).clean()

    def test_hr_can_override(self):
        horilla_middlewares._thread_locals.request = SimpleNamespace(
            user=make_user("hradmin", is_superuser=True), GET={}, session={}
        )
        self.request(2, 5).clean()


@override_settings(**SYNC_MAIL)
class BrandedEmailTests(RulesBase):
    def test_every_template_renders_with_brand_and_no_leftover_placeholders(self):
        sample = {k: "x" for k in [
            "employee", "leave_type", "start_date", "end_date", "days", "reason",
            "reject_reason", "kind", "date", "summary", "shift", "recorded", "hours",
            "out_time", "comment", "requested_out", "status", "manager_comment",
            "project", "description", "path", "role", "task", "task_type", "priority",
            "due", "period", "asset", "asset_id",
        ]}
        for key in TEMPLATES:
            subject, html = render_branded(key, sample)
            self.assertIn("INFISETU", html, key)
            self.assertNotIn("{{", subject + html, key)
            self.assertNotIn("Horilla", subject + html, key)

    def test_leave_events_send_mail(self):
        lt = LeaveType.objects.get(name="Casual Leave")
        AvailableLeave.objects.create(
            employee_id=self.employee, leave_type_id=lt, available_days=5
        )
        day = datetime.date.today() + datetime.timedelta(days=20)
        leave = LeaveRequest.objects.create(
            employee_id=self.employee, leave_type_id=lt, start_date=day,
            end_date=day, description="Appointment",
        )
        self.assertEqual(mail.outbox[-1].to, ["manager@example.com"])
        self.assertIn("Leave request from", mail.outbox[-1].subject)
        leave.status = "approved"
        leave.save()
        self.assertEqual(mail.outbox[-1].to, ["staff@example.com"])
        self.assertIn("approved", mail.outbox[-1].subject)
