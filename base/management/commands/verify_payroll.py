"""
Verify payroll against hand-calculated figures for a full month.

Uses the two sample employees from onboard_sample_employees and builds a
complete September 2026 for them (weekly offs from the company calendar, one
test holiday, one approved paid leave, two absent days), then checks:

  * the attendance summary (present / leave / week-off / holiday / absent)
  * loss of pay and basic pay against an independent calculation
  * that the individual and bulk payslip paths agree
  * that the saved payslips match

    python manage.py seed_infisetu_setup
    python manage.py onboard_sample_employees
    python manage.py verify_payroll
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from attendance.models import Attendance, AttendanceActivity
from attendance.views.summary import build_monthly_summary
from base.methods import is_company_leave
from base.models import Holidays
from employee.models import Employee
from leave.models import AvailableLeave, LeaveRequest, LeaveType
from payroll.methods.payroll_run import payroll_calculation
from payroll.models.models import Contract, Payslip

MONTH_START = datetime.date(2026, 9, 1)
MONTH_END = datetime.date(2026, 9, 30)
TEST_HOLIDAY = datetime.date(2026, 9, 15)  # Tuesday
PAID_LEAVE = datetime.date(2026, 9, 17)  # Thursday, Casual Leave
ABSENT_DAYS = {  # Aarav only
    datetime.date(2026, 9, 22),
    datetime.date(2026, 9, 23),
}
GROUP = "VERIFY-2026-09"


class Command(BaseCommand):
    help = "Verify payroll maths for a full month with hand-calculated expectations"

    def expect(self, cond, label):
        self.n += 1
        if not cond:
            raise CommandError(f"FAILED check {self.n}: {label}")
        self.stdout.write(f"  [{self.n:02d}] ok  {label}")

    def handle(self, *args, **options):
        self.n = 0
        admin = get_user_model().objects.filter(is_superuser=True).first()
        self.client = Client(HTTP_HOST="localhost")
        self.client.force_login(admin)
        aarav = Employee.objects.get(email="aarav.mehta@example.com")
        diya = Employee.objects.get(email="diya.shah@example.com")

        holiday, _ = Holidays.objects.get_or_create(
            name="TEST Holiday (verify_payroll)",
            start_date=TEST_HOLIDAY,
            defaults={"end_date": TEST_HOLIDAY},
        )
        try:
            self.prepare(aarav, 60000, absent=ABSENT_DAYS, leave_day=PAID_LEAVE)
            self.prepare(diya, 45000, absent=set(), leave_day=None)
            self.verify(aarav, 60000, absent=len(ABSENT_DAYS), paid_leave=1)
            self.verify(diya, 45000, absent=0, paid_leave=0)
            self.saved_payslips(aarav, diya)
        finally:
            holiday.delete()
        self.stdout.write(self.style.SUCCESS("\nPayroll verified."))

    # ------------------------------------------------------------------
    def working_days(self):
        days, d = [], MONTH_START
        while d <= MONTH_END:
            if not is_company_leave(d) and d != TEST_HOLIDAY:
                days.append(d)
            d += datetime.timedelta(days=1)
        return days

    def prepare(self, employee, wage, absent, leave_day):
        contract = Contract.objects.get(employee_id=employee, contract_status="active")
        contract.contract_start_date = datetime.date(2026, 8, 1)
        contract.wage = wage
        contract.save()
        Attendance.objects.filter(
            employee_id=employee,
            attendance_date__range=(MONTH_START, MONTH_END),
        ).delete()
        AttendanceActivity.objects.filter(
            employee_id=employee,
            attendance_date__range=(MONTH_START, MONTH_END),
        ).delete()
        LeaveRequest.objects.filter(
            employee_id=employee, start_date__range=(MONTH_START, MONTH_END)
        ).delete()
        shift = employee.employee_work_info.shift_id
        for day in self.working_days():
            if day in absent or day == leave_day:
                continue
            Attendance.objects.create(
                employee_id=employee,
                shift_id=shift,
                attendance_date=day,
                attendance_day=self.day_obj(day),
                attendance_clock_in="10:00:00",
                attendance_clock_in_date=day,
                attendance_clock_out="19:00:00",
                attendance_clock_out_date=day,
                attendance_worked_hour="09:00",
                minimum_hour="08:00",
                attendance_validated=True,
            )
        if leave_day:
            cl = LeaveType.objects.get(name="Casual Leave")
            AvailableLeave.objects.filter(employee_id=employee, leave_type_id=cl).update(
                available_days=2
            )
            lr = LeaveRequest.objects.create(
                employee_id=employee,
                leave_type_id=cl,
                start_date=leave_day,
                end_date=leave_day,
                description="Verify payroll",
                status="requested",
            )
            self.client.post(f"/leave/request-approve/{lr.pk}/", HTTP_HX_REQUEST="true")
            lr.refresh_from_db()
            self.expect(lr.status == "approved", f"{employee.get_full_name()}: CL approved")

    @staticmethod
    def day_obj(day):
        from base.models import EmployeeShiftDay

        return EmployeeShiftDay.objects.get(day=day.strftime("%A").lower())

    # ------------------------------------------------------------------
    def verify(self, employee, wage, absent, paid_leave):
        name = employee.get_full_name()
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{name}"))
        working = len(self.working_days())
        week_offs = sum(
            1
            for i in range(30)
            if is_company_leave(MONTH_START + datetime.timedelta(days=i))
        )
        self.expect(week_offs == 6, f"September has 6 weekly offs (4 Sundays + 2nd/4th Saturday)")
        present = working - absent - paid_leave

        rows, _tw, _totals = build_monthly_summary(MONTH_START, MONTH_END, Employee.objects.filter(pk=employee.pk))
        row = rows[0]
        self.expect(row["present"] == present, f"present days = {present} (got {row['present']})")
        self.expect(row["absent"] == absent, f"absent days = {absent} (got {row['absent']})")
        self.expect(row["paid_leave"] == paid_leave, f"paid leave days = {paid_leave}")
        self.expect(row["week_off"] == 6, f"week-off days = 6 (got {row['week_off']})")
        self.expect(row["holiday"] == 1, f"holiday days = 1 (got {row['holiday']})")

        daily = wage / 30  # contract divisor: calendar days of September
        expected_lop = round(daily * absent, 2)
        expected_basic = round(wage - expected_lop, 2)

        bulk = payroll_calculation(employee, MONTH_START, MONTH_END, month_summary=row)
        for label, calc in (("calculation", bulk),):
            self.expect(
                abs(float(calc["loss_of_pay"]) - expected_lop) < 0.01,
                f"{label}: loss of pay {calc['loss_of_pay']:.2f} == expected {expected_lop:.2f}",
            )
            self.expect(
                abs(float(calc["basic_pay"]) - expected_basic) < 0.01,
                f"{label}: basic pay {float(calc['basic_pay']):.2f} == expected {expected_basic:.2f}",
            )

        self.expect(
            float(bulk["net_pay"]) <= float(bulk["gross_pay"]) + 0.01
            and float(bulk["gross_pay"]) >= expected_basic - 0.01,
            f"gross {float(bulk['gross_pay']):.2f} >= basic and net <= gross",
        )

    # ------------------------------------------------------------------
    def saved_payslips(self, aarav, diya):
        self.stdout.write(self.style.MIGRATE_HEADING("\nSaved payslips (bulk generate)"))
        Payslip.objects.filter(group_name=GROUP).delete()
        r = self.client.post(
            "/payroll/generate-payslip/",
            {
                "employee_id": [aarav.pk, diya.pk],
                "start_date": MONTH_START.isoformat(),
                "end_date": MONTH_END.isoformat(),
                "group_name": GROUP,
            },
        )
        slips = {p.employee_id_id: p for p in Payslip.objects.filter(group_name=GROUP)}
        self.expect(len(slips) == 2, f"bulk generate saved 2 payslips (status {r.status_code})")
        a, d = slips[aarav.pk], slips[diya.pk]
        self.expect(a.gross_pay < 60000, f"Aarav gross reflects LOP ({a.gross_pay})")
        # The "Create payslip" screen must produce the same payslip as bulk.
        bulk_vals = {pk: (p.gross_pay, p.net_pay) for pk, p in slips.items()}
        Payslip.objects.filter(group_name=GROUP).delete()
        for emp in (aarav, diya):
            self.client.post(
                "/payroll/create-payslip/",
                {
                    "employee_id": emp.pk,
                    "start_date": MONTH_START.isoformat(),
                    "end_date": MONTH_END.isoformat(),
                },
                HTTP_HX_REQUEST="true",
            )
            single = Payslip.objects.get(
                employee_id=emp, start_date=MONTH_START, end_date=MONTH_END
            )
            self.expect(
                (single.gross_pay, single.net_pay) == bulk_vals[emp.pk],
                f"{emp.get_full_name()}: single-payslip screen == bulk "
                f"(gross {single.gross_pay}, net {single.net_pay})",
            )
            single.group_name = GROUP
            single.save()
        slips = {p.employee_id_id: p for p in Payslip.objects.filter(group_name=GROUP)}
        a, d = slips[aarav.pk], slips[diya.pk]
        self.expect(abs(float(d.gross_pay) - 45000) < 0.01, f"Diya gross 45000 ({d.gross_pay})")
        self.expect(a.net_pay > 0 and d.net_pay > 0, f"net pay positive (Aarav {a.net_pay}, Diya {d.net_pay})")
