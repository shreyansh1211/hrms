"""
Microsoft sign-in, exercised end to end against the development stand-in
provider (same protocol as Entra ID: authorize -> code -> token -> RS256 ID token).
"""

from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings

from horilla.testkit.factories import make_company, make_employee, make_user
from microsoft_sso import oidc

SSO = {"SSO_ENABLED": True, "SSO_DEV_MOCK": True, "DEBUG": True}


def _path(url):
    parts = urlparse(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


class _Net:
    """Routes the SSO client's outbound HTTP calls to the in-process provider."""

    def __init__(self, client):
        self.client = client

    def get(self, url):
        return self.client.get(_path(url))

    def post(self, url, data):
        return self.client.post(_path(url), data)


@override_settings(**SSO)
class SsoFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = make_company("InfiSetu Technologies")
        cls.company = company
        cls.employee = make_employee(
            company=company, email="Aarav.Mehta@Infisetu.com", first_name="Aarav"
        )
        cls.user = cls.employee.employee_user_id
        cls.user.is_new_employee = True
        cls.user.save()

    def setUp(self):
        net = _Net(self.client)
        patches = [
            mock.patch.object(oidc, "http_get", net.get),
            mock.patch.object(oidc, "http_post", net.post),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # -- helpers --------------------------------------------------------
    def begin(self):
        response = self.client.get("/sso/login/")
        self.assertEqual(response.status_code, 302)
        authorize = response["Location"]
        self.assertIn("/dev-idp/dev-tenant/oauth2/v2.0/authorize", authorize)
        query = parse_qs(urlparse(authorize).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        return authorize, {k: v[0] for k, v in query.items()}

    def pick(self, authorize, params, email):
        response = self.client.post(_path(authorize), {**params, "email": email})
        self.assertEqual(response.status_code, 302)
        return response["Location"]

    # -- tests -------------------------------------------------------------------
    def test_login_page_shows_the_microsoft_button(self):
        # A superuser without an employee puts the page in first-run setup mode.
        admin = make_user("admin", is_superuser=True)
        make_employee(company=self.company, email="admin@infisetu.com", user=admin)
        page = self.client.get("/login/")
        self.assertContains(page, "Sign in with Microsoft")

    def test_full_sign_in_matches_employee_email_case_insensitively(self):
        authorize, params = self.begin()
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        response = self.client.get(_path(callback))
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_new_employee)  # no forced password change

    def test_unknown_email_is_refused_and_nothing_is_created(self):
        from employee.models import Employee

        authorize, params = self.begin()
        callback = self.pick(authorize, params, "stranger@infisetu.com")
        response = self.client.get(_path(callback), follow=False)
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(Employee.objects.filter(email="stranger@infisetu.com").count(), 0)

    def test_wrong_state_is_rejected(self):
        authorize, params = self.begin()
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        tampered = callback.replace("state=", "state=x")
        self.client.get(_path(tampered))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_cannot_be_replayed(self):
        authorize, params = self.begin()
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        self.client.get(_path(callback))
        self.client.logout()
        self.client.get(_path(callback))  # same code again, no flow in session
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_token_for_another_audience_is_rejected(self):
        authorize, params = self.begin()
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        with override_settings(ENTRA_CLIENT_ID="someone-else"), mock.patch(
            "microsoft_sso.conf.client_id", return_value="someone-else"
        ):
            self.client.get(_path(callback))
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(SSO_ALLOWED_DOMAINS="otherco.com")
    def test_domain_allow_list(self):
        authorize, params = self.begin()
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        self.client.get(_path(callback))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_employee_cannot_sign_in(self):
        self.user.is_active = False
        self.user.save()
        authorize, params = self.begin()
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        self.client.get(_path(callback))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_open_redirect_is_ignored(self):
        response = self.client.get("/sso/login/?next=https://evil.example/")
        authorize = response["Location"]
        params = {k: v[0] for k, v in parse_qs(urlparse(authorize).query).items()}
        callback = self.pick(authorize, params, "aarav.mehta@infisetu.com")
        response = self.client.get(_path(callback))
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class SsoDisabledTests(TestCase):
    @override_settings(SSO_ENABLED=False)
    def test_endpoints_404_when_disabled(self):
        self.assertEqual(self.client.get("/sso/login/").status_code, 404)
        self.assertEqual(self.client.get("/sso/callback/").status_code, 404)

    @override_settings(SSO_ENABLED=True, SSO_DEV_MOCK=True, DEBUG=False)
    def test_stand_in_provider_is_off_outside_debug(self):
        self.assertEqual(
            self.client.get("/dev-idp/dev-tenant/discovery/v2.0/keys").status_code, 404
        )
