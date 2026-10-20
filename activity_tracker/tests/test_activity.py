import datetime
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone

from activity_tracker import client, sync
from activity_tracker.models import ActiveTimeDay
from attendance.models import Attendance
from horilla.testkit.factories import make_company, make_employee, make_user

TRACKER = {
    "ACTIVITY_TRACKER_URL": "http://127.0.0.1:8001",
    "ACTIVITY_TRACKER_API_KEY": "itm_testkey",
    "ACTIVITY_TRACKER_CONSOLE_URL": "https://time.example.com",
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


def tracker_payload(day):
    iso = day.isoformat()
    return {
        "employees": [
            {
                "employee": {"id": 7, "external_id": "B-100", "email": "x@x.com", "name": "By badge"},
                "agent": {"status": "online"},
                "days": [{"date": iso, "active_seconds": 3 * 3600 + 30 * 60,
                          "tracked_seconds": 8 * 3600, "first_seen": 1790000000, "last_seen": 1790028800}],
            },
            {
                "employee": {"id": 8, "external_id": None, "email": "Dana@Example.com", "name": "By mail"},
                "agent": {"status": "offline"},
                "days": [{"date": iso, "active_seconds": 600, "tracked_seconds": 900,
                          "first_seen": None, "last_seen": None}],
            },
            {
                "employee": {"id": 9, "external_id": "NOPE", "email": "ghost@example.com", "name": "Ghost"},
                "agent": {"status": "online"},
                "days": [{"date": iso, "active_seconds": 5, "tracked_seconds": 5,
                          "first_seen": None, "last_seen": None}],
            },
        ]
    }


@override_settings(**TRACKER)
class ActivityTrackerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("InfiSetu Technologies")
        cls.badge = make_employee(company=company, email="badge@example.com", first_name="Bea")
        cls.badge.badge_id = "B-100"
        cls.badge.save()
        cls.mail = make_employee(company=company, email="dana@example.com", first_name="Dana")
        cls.admin_user = make_user("boss", is_superuser=True)
        make_employee(company=company, email="boss@example.com", user=cls.admin_user, first_name="Boss")
        cls.today = datetime.date.today()
        for emp in (cls.badge, cls.mail):  # skip the forced first-login password change
            emp.employee_user_id.is_new_employee = False
            emp.employee_user_id.save()

    def run_sync(self, payload=None):
        payload = payload or tracker_payload(self.today)
        with mock.patch.object(client, "http_get", return_value=FakeResponse(payload)) as get:
            result = sync.sync_recent(1)
        return result, get

    def test_sync_matches_by_badge_then_email_and_reports_unmatched(self):
        (saved, unmatched), get = self.run_sync()
        self.assertEqual(saved, 2)
        self.assertEqual(unmatched, ["Ghost"])
        self.assertEqual(
            ActiveTimeDay.objects.get(employee_id=self.badge, date=self.today).active_seconds, 12600
        )
        self.assertTrue(ActiveTimeDay.objects.filter(employee_id=self.mail).exists())
        headers = get.call_args[0][2]
        self.assertEqual(headers["Authorization"], "Bearer itm_testkey")

    def test_external_id_may_hold_the_email(self):
        payload = tracker_payload(self.today)
        payload["employees"][2]["employee"].update(
            {"external_id": "Dana@example.com", "email": "other@elsewhere.com"}
        )
        payload["employees"][1]["employee"]["email"] = "nobody@elsewhere.com"
        (saved, unmatched), _ = self.run_sync(payload)
        self.assertEqual(saved, 2)  # Bea by badge, Dana by e-mail held in external_id
        self.assertEqual(unmatched, ["By mail"])

    def test_sync_is_idempotent_and_updates(self):
        self.run_sync()
        payload = tracker_payload(self.today)
        payload["employees"][0]["days"][0]["active_seconds"] = 7200
        self.run_sync(payload)
        self.assertEqual(ActiveTimeDay.objects.filter(employee_id=self.badge).count(), 1)
        self.assertEqual(ActiveTimeDay.objects.get(employee_id=self.badge).active_seconds, 7200)

    def test_tracker_errors_are_reported_not_raised_to_the_scheduler(self):
        from activity_tracker.scheduler import sync_active_time

        with mock.patch.object(client, "http_get", return_value=FakeResponse({}, 500)):
            sync_active_time()  # logs a warning, no exception

    @override_settings(ACTIVITY_TRACKER_API_KEY="")
    def test_unconfigured_does_nothing(self):
        from activity_tracker.scheduler import sync_active_time

        with mock.patch.object(client, "http_get") as get:
            sync_active_time()
        get.assert_not_called()

    def test_employee_sees_only_their_own_three_times(self):
        self.run_sync()
        Attendance.objects.create(
            employee_id=self.badge, attendance_date=self.today,
            attendance_clock_in="09:00:00", attendance_clock_in_date=self.today,
            attendance_clock_out="17:00:00", attendance_clock_out_date=self.today,
            attendance_worked_hour="08:00",
        )
        self.client.force_login(self.badge.employee_user_id)
        body = self.client.get("/activity/my-time/").json()
        self.assertEqual(body["today"]["in"], "8h 00m")
        self.assertEqual(body["today"]["active"], "3h 30m")
        self.assertEqual(body["today"]["project"], "0h 00m")
        self.assertNotIn("tracked", body["today"])  # employees get no detail

    def test_team_table_requires_permission(self):
        self.run_sync()
        self.client.force_login(self.badge.employee_user_id)
        self.assertEqual(self.client.get("/activity/team/").status_code, 403)
        self.assertEqual(self.client.post("/activity/team/sync/").status_code, 403)

        self.badge.employee_user_id.user_permissions.add(
            Permission.objects.get(codename="view_activetimeday")
        )
        page = self.client.get("/activity/team/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Bea")
        self.assertContains(page, "3h 30m")
        self.assertContains(page, "https://time.example.com/employees/7")

    def test_superuser_can_trigger_a_sync(self):
        self.client.force_login(self.admin_user)
        with mock.patch.object(client, "http_get", return_value=FakeResponse(tracker_payload(self.today))):
            response = self.client.post("/activity/team/sync/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ActiveTimeDay.objects.exists())
