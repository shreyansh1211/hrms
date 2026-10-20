"""
Seed Infisetu's reference data: shifts, work/employee types, Indian holidays,
SL/PL/CL leave types, recruitment skills and reject reasons.

Idempotent -- safe to run repeatedly.
    python manage.py seed_infisetu_setup
"""

import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand

from base.models import (
    Company,
    CompanyLeaves,
    EmployeeShift,
    EmployeeShiftDay,
    EmployeeShiftSchedule,
    EmployeeType,
    Holidays,
    WorkType,
)
from leave.models import LeaveType
from recruitment.models import RejectReason, Skill

T = datetime.time

# name, start, end, is_night
SHIFTS = [
    ("Morning (10 AM - 7 PM)", T(10, 0), T(19, 0), False),
    ("Morning (11 AM - 8 PM)", T(11, 0), T(20, 0), False),
    ("Noon (2 PM - 11 PM)", T(14, 0), T(23, 0), False),
    ("Evening (4 PM - 1 AM)", T(16, 0), T(1, 0), True),
    ("Night (6 PM - 3 AM)", T(18, 0), T(3, 0), True),
]
DAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

# name, date, recurring every year
HOLIDAYS = [
    ("Diwali (Lakshmi Puja)", datetime.date(2026, 11, 8), False),
    ("Bhai Dooj", datetime.date(2026, 11, 11), False),
    ("Guru Nanak Jayanti", datetime.date(2026, 11, 24), False),
    ("Christmas", datetime.date(2026, 12, 25), True),
    ("Republic Day", datetime.date(2027, 1, 26), True),
    ("Independence Day", datetime.date(2027, 8, 15), True),
    ("Gandhi Jayanti", datetime.date(2027, 10, 2), True),
]

# Credited 2 days every four months (see leave.scheduler.leave_accrual)
LEAVE_TYPES = ["Sick Leave", "Privilege Leave", "Casual Leave"]

SKILLS = [
    "Python", "Django", "PHP", "Laravel", "WordPress", "JavaScript", "TypeScript",
    "React", "Node.js", "HTML/CSS", "MySQL", "PostgreSQL", "Git", "REST API",
    "Figma", "UI/UX Design", "Adobe Photoshop", "Adobe Illustrator",
    "Manual Testing", "Selenium", "SEO", "Communication", "Client Handling",
]
REJECT_REASONS = [
    "Skills do not match the role",
    "Failed technical test",
    "Failed technical interview",
    "Salary expectation too high",
    "Notice period too long",
    "Not interested / withdrew",
    "Did not respond",
    "Position filled",
]


class Command(BaseCommand):
    help = "Seed shifts, work types, holidays, leave types and recruitment basics"

    def handle(self, *args, **options):
        company = Company.objects.first()
        self._work_types()
        self._shifts()
        self._holidays(company)
        self._weekly_offs(company)
        self._grace_time()
        self._leave_types(company)
        for title in SKILLS:
            Skill.objects.get_or_create(title=title)
        for title in REJECT_REASONS:
            RejectReason.objects.get_or_create(
                title=title, defaults={"description": title}
            )
        call_command("seed_email_templates", stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Infisetu setup data is in place."))

    def _work_types(self):
        for name in ["Work From Office", "Work From Home", "Hybrid"]:
            WorkType.objects.get_or_create(work_type=name)
        for name in ["Full-time", "Trainee / Intern", "Contract"]:
            EmployeeType.objects.get_or_create(employee_type=name)

    def _shifts(self):
        for name, start, end, night in SHIFTS:
            shift, _ = EmployeeShift.objects.get_or_create(employee_shift=name)
            for day in DAYS:
                day_obj, _ = EmployeeShiftDay.objects.get_or_create(day=day)
                EmployeeShiftSchedule.objects.update_or_create(
                    day=day_obj,
                    shift_id=shift,
                    defaults={
                        "start_time": start,
                        "end_time": end,
                        "is_night_shift": night,
                        "minimum_working_hour": "08:15",  # 9h shift - 45 min break
                    },
                )
        self.stdout.write(f"Shifts: {len(SHIFTS)} x {len(DAYS)} days")

    def _grace_time(self):
        """30 minutes of grace on check-in and check-out; beyond it an intimation is raised."""
        from attendance.models import GraceTime

        grace = GraceTime.objects.filter(is_default=True).first() or GraceTime()
        grace.allowed_time = "00:30:00"
        grace.allowed_time_in_secs = 30 * 60
        grace.allowed_clock_in = True
        grace.allowed_clock_out = True
        grace.is_default = True
        grace.save()
        self.stdout.write("Grace time: 30 minutes (check-in and check-out)")

    def _weekly_offs(self, company):
        """Every Sunday, plus the 2nd and 4th Saturday of each month."""
        offs = [(None, "6"), ("1", "5"), ("3", "5")]  # (week of month, weekday)
        for week, weekday in offs:
            off, _ = CompanyLeaves.objects.get_or_create(
                based_on_week=week, based_on_week_day=weekday
            )
            if company:
                off.company_id.add(company)
        self.stdout.write("Weekly offs: Sundays, 2nd and 4th Saturdays")

    def _holidays(self, company):
        for name, day, recurring in HOLIDAYS:
            Holidays.objects.update_or_create(
                name=name,
                start_date=day,
                defaults={
                    "end_date": day,
                    "recurring": recurring,
                    "company_id": company,
                },
            )
        self.stdout.write(f"Holidays: {len(HOLIDAYS)}")

    def _leave_types(self, company):
        for name in LEAVE_TYPES:
            LeaveType.objects.update_or_create(
                name=name,
                defaults={
                    "payment": "paid",
                    "count": 2,
                    "period_in": "day",
                    "limit_leave": True,
                    "total_days": 2,
                    "reset": False,
                    "carryforward_type": "no carryforward",
                    "require_approval": "yes",
                    "exclude_company_leave": "yes",
                    "exclude_holiday": "yes",
                    "company_id": company,
                },
            )
        self.stdout.write(f"Leave types: {', '.join(LEAVE_TYPES)}")
