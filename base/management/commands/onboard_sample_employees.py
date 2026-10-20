"""
Run two sample employees through the complete HR flow and verify every stage:

  recruitment -> candidate -> stages -> offer -> onboarding portal (candidate
  sets password, uploads photo, fills personal + bank details) -> HR completes
  work info (shift, work type, manager) -> contract / salary -> leave balances
  -> login -> attendance check-in/out -> leave request -> payslip.

Uses the real views through the Django test client, so it doubles as a smoke
test.  Idempotent: stages already done are skipped.

    python manage.py seed_infisetu_setup
    python manage.py onboard_sample_employees
"""

import datetime
import io

from PIL import Image

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from attendance.models import Attendance, AttendanceGeneralSetting
from base.models import (
    Company,
    EmployeeShift,
    EmployeeType,
    JobPosition,
    WorkType,
)
from employee.models import Employee, EmployeeBankDetails
from leave.models import AvailableLeave, LeaveRequest, LeaveType
from onboarding.models import OnboardingPortal, OnboardingStage, OnboardingTask
from payroll.models.models import Contract, Payslip
from recruitment.models import Candidate, Recruitment, Skill, Stage

HOST = "localhost"
PASSWORD = "Infisetu@2026!"

# example.com is reserved for documentation: no real mailbox can receive mail.
SAMPLES = [
    {
        "name": "Aarav Mehta",
        "email": "aarav.mehta@example.com",
        "phone": "9000000001",
        "gender": "male",
        "dob": "1996-04-12",
        "position": "Full Stack Developer",
        "skills": ["Python", "Django", "React", "PostgreSQL", "Git"],
        "shift": "Morning (10 AM - 7 PM)",
        "work_type": "Work From Office",
        "employee_type": "Full-time",
        "wage": 60000,
        "experience": 3,
        "qualification": "B.E. Computer Engineering",
        "bank": ("HDFC Bank", "50100000000001", "Ahmedabad Main", "HDFC0000001"),
    },
    {
        "name": "Diya Shah",
        "email": "diya.shah@example.com",
        "phone": "9000000002",
        "gender": "female",
        "dob": "1998-09-03",
        "position": "UI UX Developer",
        "skills": ["Figma", "UI/UX Design", "HTML/CSS", "Adobe Illustrator"],
        "shift": "Morning (11 AM - 8 PM)",
        "work_type": "Work From Office",
        "employee_type": "Full-time",
        "wage": 45000,
        "experience": 2,
        "qualification": "B.Des. Interaction Design",
        "bank": ("ICICI Bank", "000405000002", "Ahmedabad Main", "ICIC0000004"),
    },
]

RECRUITMENT_STAGES = [
    ("Applied", "applied"),
    ("HR Screening", "initial"),
    ("Technical Test", "test"),
    ("Technical Interview", "interview"),
    ("HR Interview", "interview"),
    ("Selected / Hired", "hired"),
]
ONBOARDING_STAGES = {
    "Document Collection": [
        "Collect ID, address and education documents",
        "Collect bank details and cancelled cheque",
        "Sign offer letter and NDA",
    ],
    "IT Setup": [
        "Create Microsoft account and email",
        "Allocate laptop, mouse and keyboard",
        "Add to GitHub and project tools",
    ],
    "Orientation": [
        "Introduction to team and reporting manager",
        "Company policies and leave process",
    ],
    "Joined": ["Confirm first day attendance"],
}


class Flow:
    def __init__(self, command):
        self.cmd = command
        self.n = 0

    def ok(self, cond, label):
        self.n += 1
        if not cond:
            raise CommandError(f"FAILED stage {self.n}: {label}")
        self.cmd.stdout.write(f"  [{self.n:02d}] ok  {label}")


class Command(BaseCommand):
    help = "Onboard two sample employees through the full flow, verifying each stage"

    def handle(self, *args, **options):
        User = get_user_model()
        admin = User.objects.filter(is_superuser=True).first()
        if admin is None or not hasattr(admin, "employee_get"):
            raise CommandError("Need a superuser linked to an employee.")
        self.manager = admin.employee_get
        self.company = Company.objects.first()
        self.admin_client = Client(HTTP_HOST=HOST)
        self.admin_client.force_login(admin)
        AttendanceGeneralSetting.objects.get_or_create(
            company_id=self.company, defaults={"enable_check_in": True}
        )
        AttendanceGeneralSetting.objects.filter(company_id=self.company).update(
            enable_check_in=True
        )
        for sample in SAMPLES:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{sample['name']}"))
            self.run_flow(sample, Flow(self))
        self.stdout.write(
            self.style.SUCCESS(
                f"\nBoth employees verified. Temporary password: {PASSWORD} "
                "(they must change it)."
            )
        )

    # ------------------------------------------------------------------
    def run_flow(self, s, f):
        position = JobPosition.objects.get(job_position=s["position"])
        recruitment = self.recruitment(position, s, f)
        candidate = self.candidate(recruitment, s, f)
        employee = self.onboarding(candidate, s, f)
        self.hr_completion(employee, s, f)
        self.contract(employee, s, f)
        self.leave_balances(employee, f)
        client = self.login(employee, s, f)
        self.attendance(client, employee, f)
        self.leave_request(employee, f)
        self.payslip(employee, f)

    # --- 1. recruitment ----------------------------------------------------
    def recruitment(self, position, s, f):
        rec, _ = Recruitment.objects.get_or_create(
            title=f"{s['position']} - Hiring",
            defaults={
                "description": f"Opening for {s['position']}",
                "job_position_id": position,
                "company_id": self.company,
                "vacancy": 1,
                "start_date": datetime.date.today(),
                "is_published": False,
            },
        )
        rec.recruitment_managers.add(self.manager)
        rec.skills.add(*Skill.objects.filter(title__in=s["skills"]))
        for seq, (title, kind) in enumerate(RECRUITMENT_STAGES, start=1):
            Stage.objects.get_or_create(
                recruitment_id=rec,
                stage=title,
                defaults={"stage_type": kind, "sequence": seq},
            )
        for seq, (title, tasks) in enumerate(ONBOARDING_STAGES.items(), start=1):
            stage, _ = OnboardingStage.objects.get_or_create(
                recruitment_id=rec,
                stage_title=title,
                defaults={"sequence": seq, "is_final_stage": title == "Joined"},
            )
            for task in tasks:
                OnboardingTask.objects.get_or_create(
                    stage_id=stage, task_title=task, defaults={"is_required": True}
                )
        # Horilla auto-creates "Applied" and "Initial" stages for every recruitment.
        f.ok(rec.stage_set.count() >= 6, "recruitment created with its hiring stages")
        f.ok(rec.onboarding_stage.count() >= 4, "onboarding checklist created")
        return rec

    # --- 2. candidate through the hiring stages ---------------------------------
    def candidate(self, rec, s, f):
        cand = Candidate.objects.filter(email=s["email"], recruitment_id=rec).first()
        if cand is None:
            cand = Candidate(
                name=s["name"],
                email=s["email"],
                mobile=s["phone"],
                gender=s["gender"],
                dob=s["dob"],
                address="Ahmedabad, Gujarat",
                country="India",
                state="Gujarat",
                recruitment_id=rec,
                job_position_id=rec.job_position_id,
                stage_id=rec.stage_set.get(stage="Applied"),
                source="application",
            )
            cand.resume.save(
                f"{s['name'].replace(' ', '_')}_resume.pdf",
                SimpleUploadedFile("r.pdf", b"%PDF-1.4 sample resume"),
                save=False,
            )
            cand.save()
        f.ok(cand.pk is not None, "candidate applied")
        for title, kind in RECRUITMENT_STAGES[1:]:
            cand.stage_id = rec.stage_set.get(stage=title)
            cand.save()
            cand.refresh_from_db()
            f.ok(cand.stage_id.stage == title, f"moved to stage '{title}'")
        f.ok(cand.hired, "candidate marked hired")
        cand.offer_letter_status = "accepted"
        cand.joining_date = datetime.date.today()
        cand.probation_end = datetime.date.today() + datetime.timedelta(days=180)
        cand.save()
        f.ok(cand.offer_letter_status == "accepted", "offer letter accepted")
        return cand

    # --- 3. onboarding portal -------------------------------------------------------
    def onboarding(self, cand, s, f):
        if cand.converted_employee_id:
            f.ok(True, "already converted to employee (skipping onboarding)")
            return cand.converted_employee_id
        r = self.admin_client.post(
            "/onboarding/email-send/?no_portal=True", {"ids": [cand.pk]}
        )
        cand.refresh_from_db()
        f.ok(cand.start_onboard, "onboarding started")
        portal = OnboardingPortal.objects.get(candidate_id=cand)
        token = portal.token
        c = Client(HTTP_HOST=HOST)
        r = c.post(
            f"/onboarding/user-creation/{token}/",
            {"password1": PASSWORD, "password2": PASSWORD},
        )
        f.ok(r.status_code == 302, "candidate created portal account")
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (1, 115, 145)).save(buf, "PNG")
        photo = SimpleUploadedFile("me.png", buf.getvalue(), content_type="image/png")
        r = c.post(f"/onboarding/profile-view/{token}/", {"profile": photo})
        portal.refresh_from_db()
        f.ok(portal.count == 2, "candidate uploaded profile photo")
        r = c.post(
            f"/onboarding/employee-creation/{token}/",
            {
                "employee_first_name": s["name"].split()[0],
                "employee_last_name": s["name"].split()[1],
                "phone": s["phone"],
                "address": "12 Satellite Road, Ahmedabad",
                "country": "India",
                "state": "Gujarat",
                "city": "Ahmedabad",
                "zip": "380015",
                "dob": s["dob"],
                "gender": s["gender"],
                "qualification": s["qualification"],
                "experience": s["experience"],
                "marital_status": "single",
                "children": 0,
                "emergency_contact": "9000000099",
                "emergency_contact_name": "Family Contact",
                "emergency_contact_relation": "Parent",
            },
        )
        f.ok(r.status_code == 302, f"personal details saved ({r.status_code})")
        if "_auth_user_id" not in c.session:
            # The portal logs the candidate in after this step; if the session
            # did not carry over, sign in the way the candidate would.
            self.stdout.write("  note: portal session not carried over; logging in")
            c.post("/login/", {"username": s["email"], "password": PASSWORD})
        bank = s["bank"]
        r = c.post(
            f"/onboarding/employee-bank-details/{token}/",
            {
                "bank_name": bank[0],
                "account_number": bank[1],
                "branch": bank[2],
                "address": "Ahmedabad",
                "country": "India",
                "state": "Gujarat",
                "city": "Ahmedabad",
                "any_other_code1": bank[3],
            },
        )
        cand.refresh_from_db()
        employee = cand.converted_employee_id
        f.ok(employee is not None, "candidate converted to employee")
        f.ok(
            EmployeeBankDetails.objects.filter(employee_id=employee).exists(),
            "bank details stored",
        )
        f.ok(
            employee.employee_work_info.reporting_manager_id == self.manager,
            "onboarding set the reporting manager from the recruitment manager",
        )
        f.ok(
            AvailableLeave.objects.filter(employee_id=employee).count() == 3,
            "onboarding assigned SL / PL / CL balances",
        )
        return employee

    # --- 4. HR completes the work information ------------------------------------------
    def hr_completion(self, employee, s, f):
        wi = employee.employee_work_info
        wi.shift_id = EmployeeShift.objects.get(employee_shift=s["shift"])
        wi.work_type_id = WorkType.objects.get(work_type=s["work_type"])
        wi.employee_type_id = EmployeeType.objects.get(employee_type=s["employee_type"])
        wi.reporting_manager_id = self.manager
        wi.location = "Head Office"
        wi.date_joining = wi.date_joining or datetime.date.today()
        wi.basic_salary = s["wage"]
        wi.company_id = self.company
        wi.save()
        wi.refresh_from_db()
        f.ok(wi.shift_id.employee_shift == s["shift"], f"shift: {s['shift']}")
        f.ok(wi.department_id and wi.job_position_id, "department and position set")
        f.ok(wi.reporting_manager_id == self.manager, "reporting manager set")

    # --- 5. contract / salary ---------------------------------------------------------------------
    def contract(self, employee, s, f):
        wi = employee.employee_work_info
        # Horilla may already have created a contract for the new employee.
        contract = Contract.objects.filter(employee_id=employee).first()
        if contract is None:
            contract = Contract(
                employee_id=employee,
                contract_name=f"{employee.get_full_name()} - Employment",
            )
        contract.contract_start_date = contract.contract_start_date or wi.date_joining
        contract.wage_type = "monthly"
        contract.pay_frequency = "monthly"
        contract.wage = s["wage"]
        contract.monthly_ctc = s["wage"]
        contract.contract_status = "active"
        contract.department = wi.department_id
        contract.job_position = wi.job_position_id
        contract.shift = wi.shift_id
        contract.work_type = wi.work_type_id
        contract.save()
        f.ok(
            Contract.objects.filter(employee_id=employee, contract_status="active").count() == 1,
            f"exactly one active contract, wage {s['wage']}",
        )

    # --- 6. leave balances ----------------------------------------------------------------------
    def leave_balances(self, employee, f):
        for lt in LeaveType.objects.filter(
            name__in=["Sick Leave", "Privilege Leave", "Casual Leave"]
        ):
            AvailableLeave.objects.get_or_create(
                employee_id=employee,
                leave_type_id=lt,
                defaults={"available_days": lt.total_days},
            )
        days = dict(
            AvailableLeave.objects.filter(employee_id=employee).values_list(
                "leave_type_id__name", "available_days"
            )
        )
        f.ok(
            all(days.get(n, 0) >= 2 for n in ("Sick Leave", "Privilege Leave", "Casual Leave")),
            "SL / PL / CL balances assigned (2 each)",
        )

    # --- 7. login --------------------------------------------------------------------------------------
    def login(self, employee, s, f):
        c = Client(HTTP_HOST=HOST)
        r = c.post("/login/", {"username": s["email"], "password": PASSWORD})
        f.ok(
            r.status_code == 302 and "_auth_user_id" in c.session,
            "employee can log in with email + password",
        )
        r = c.get("/my-dashboard/")
        f.ok(r.status_code == 200, "employee dashboard loads")
        return c

    # --- 8. attendance -------------------------------------------------------------------------------------
    def attendance(self, c, employee, f):
        r = c.post("/attendance/clock-in/", HTTP_HX_REQUEST="true", follow=True)
        att = Attendance.objects.filter(employee_id=employee).order_by("-id").first()
        f.ok(att is not None and att.attendance_clock_in, "check-in recorded")
        f.ok(
            att.shift_id == employee.employee_work_info.shift_id,
            "attendance linked to the employee's shift",
        )
        c.post("/attendance/clock-out/", HTTP_HX_REQUEST="true", follow=True)
        att.refresh_from_db()
        f.ok(att.attendance_clock_out is not None, "check-out recorded")

    # --- 9. leave request ------------------------------------------------------------------------------------
    def leave_request(self, employee, f):
        lt = LeaveType.objects.get(name="Casual Leave")
        start = datetime.date.today() + datetime.timedelta(days=14)
        while start.weekday() >= 5 or start in {
            h.start_date for h in __import__("base.models", fromlist=["Holidays"]).Holidays.objects.all()
        }:
            start += datetime.timedelta(days=1)
        lr, _ = LeaveRequest.objects.get_or_create(
            employee_id=employee,
            leave_type_id=lt,
            start_date=start,
            end_date=start,
            defaults={"description": "Personal work", "status": "requested"},
        )
        f.ok(lr.pk is not None, f"leave requested for {start}")
        if lr.status != "approved":
            self.admin_client.post(
                f"/leave/request-approve/{lr.pk}/", HTTP_HX_REQUEST="true"
            )
        lr.refresh_from_db()
        f.ok(lr.status == "approved", "manager approved the leave request")
        bal = AvailableLeave.objects.get(employee_id=employee, leave_type_id=lt)
        f.ok(bal.available_days <= 1, f"balance deducted (Casual Leave left {bal.available_days})")

    # --- 10. payslip -------------------------------------------------------------------------------------------------
    def payslip(self, employee, f):
        today = datetime.date.today()
        start = today.replace(day=1)
        r = self.admin_client.post(
            "/payroll/create-payslip/",
            {
                "employee_id": employee.pk,
                "start_date": start.isoformat(),
                "end_date": today.isoformat(),
            },
            HTTP_HX_REQUEST="true",
        )
        slip = Payslip.objects.filter(employee_id=employee).order_by("-id").first()
        f.ok(slip is not None, "payslip generated")
        f.ok(slip.gross_pay is not None and slip.gross_pay > 0, f"payslip gross pay {slip.gross_pay}")
