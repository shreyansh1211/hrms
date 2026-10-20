"""
End-to-end smoke test: seed Infisetu reference data, then onboard two employees
through recruitment -> onboarding portal -> work info -> contract -> login ->
attendance -> leave -> payroll, asserting every stage (see the
onboard_sample_employees command).
"""

import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from base.models import Department, EmployeeShift, Holidays, JobPosition
from horilla.testkit.factories import make_company, make_employee, make_user
from leave.models import LeaveType
from leave.scheduler import leave_accrual


class InfisetuFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("InfiSetu Technologies")
        admin = make_user("admin", is_superuser=True, email="admin@example.com")
        make_employee(
            company=company, email="admin@example.com", user=admin, first_name="Admin"
        )
        for dept, position in [
            ("Development", "Full Stack Developer"),
            ("Designing", "UI UX Developer"),
        ]:
            department = Department.objects.create(department=dept)
            JobPosition.objects.create(job_position=position, department_id=department)

    def test_seed_data(self):
        call_command("seed_infisetu_setup", stdout=StringIO())
        self.assertEqual(EmployeeShift.objects.count(), 5)
        self.assertEqual(
            EmployeeShift.objects.get(employee_shift="Evening (4 PM - 1 AM)")
            .employeeshiftschedule_set.filter(is_night_shift=True)
            .count(),
            7,
        )
        self.assertTrue(Holidays.objects.filter(name="Diwali (Lakshmi Puja)").exists())
        self.assertEqual(
            set(
                LeaveType.objects.filter(
                    name__in=["Sick Leave", "Privilege Leave", "Casual Leave"]
                ).values_list("total_days", flat=True)
            ),
            {2.0},
        )

    def test_full_flow_for_two_employees(self):
        call_command("seed_infisetu_setup", stdout=StringIO())
        out = StringIO()
        call_command("onboard_sample_employees", stdout=out)
        self.assertIn("Both employees verified", out.getvalue())

    def test_weekly_offs_are_sundays_and_2nd_4th_saturdays(self):
        from base.methods import get_company_leave_dates, is_company_leave

        call_command("seed_infisetu_setup", stdout=StringIO())
        saturdays = {
            d
            for d in get_company_leave_dates(2026)
            if d.weekday() == 5 and d.month in (9, 10, 11, 12)
        }
        self.assertEqual(
            sorted(d.isoformat() for d in saturdays),
            [
                "2026-09-12", "2026-09-26", "2026-10-10", "2026-10-24",
                "2026-11-14", "2026-11-28", "2026-12-12", "2026-12-26",
            ],
        )
        # attendance/leave and payroll must agree on every one of these days
        for day in get_company_leave_dates(2026):
            self.assertTrue(is_company_leave(day), day)
        self.assertFalse(is_company_leave(datetime.date(2026, 11, 7)))  # 1st Sat

    def test_payroll_matches_hand_calculation(self):
        call_command("seed_infisetu_setup", stdout=StringIO())
        call_command("onboard_sample_employees", stdout=StringIO())
        out = StringIO()
        call_command("verify_payroll", stdout=out)
        self.assertIn("Payroll verified", out.getvalue())

    def test_auto_sign_out_after_12_hours_and_email(self):
        from django.core import mail
        from django.utils import timezone

        from attendance.models import Attendance, AttendanceActivity
        from attendance.scheduler import auto_sign_out_missed
        from employee.models import Employee

        employee = Employee.objects.first()
        first_in = timezone.localtime() - datetime.timedelta(hours=15)
        day = first_in.date()
        AttendanceActivity.objects.create(
            employee_id=employee,
            attendance_date=day,
            clock_in_date=day,
            clock_in=first_in.time(),
            in_datetime=first_in,
        )
        Attendance.objects.create(
            employee_id=employee,
            attendance_date=day,
            attendance_clock_in=first_in.time(),
            attendance_clock_in_date=day,
        )
        with self.settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            BRANDED_EMAIL_SYNC=True,
        ):
            auto_sign_out_missed()
            activity = AttendanceActivity.objects.get(employee_id=employee)
            attendance = Attendance.objects.get(employee_id=employee)
            self.assertIsNotNone(activity.clock_out)
            self.assertIsNotNone(attendance.attendance_clock_out)
            self.assertEqual(attendance.attendance_worked_hour, "12:00")
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("sign", mail.outbox[0].subject.lower())
            auto_sign_out_missed()  # nothing open any more -> no second email
            self.assertEqual(len(mail.outbox), 1)

    def test_leave_accrual_every_four_months(self):
        from employee.models import Employee
        from leave.models import AvailableLeave

        call_command("seed_infisetu_setup", stdout=StringIO())
        employee = Employee.objects.first()
        sick = LeaveType.objects.get(name="Sick Leave")
        today = datetime.date.today()
        available = AvailableLeave.objects.create(
            employee_id=employee,
            leave_type_id=sick,
            available_days=2,
            assigned_date=today - datetime.timedelta(days=130),
        )
        leave_accrual()  # first run only sets the next credit date
        available.refresh_from_db()
        self.assertIsNotNone(available.reset_date)
        self.assertEqual(available.available_days, 2)
        # Four months have passed since assignment -> 2 more days are credited.
        AvailableLeave.objects.filter(pk=available.pk).update(
            reset_date=today - datetime.timedelta(days=1)
        )
        leave_accrual()
        available.refresh_from_db()
        self.assertEqual(available.available_days, 4)
        self.assertGreater(available.reset_date, today)
        leave_accrual()  # not due again -> no double credit
        available.refresh_from_db()
        self.assertEqual(available.available_days, 4)
