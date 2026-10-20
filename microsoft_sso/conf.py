"""
Microsoft Entra ID (Azure AD) sign-in configuration, read from settings / .env:

    SSO_ENABLED=True
    ENTRA_TENANT_ID=<directory (tenant) id>
    ENTRA_CLIENT_ID=<application (client) id>
    ENTRA_CLIENT_SECRET=<client secret value>
    SSO_REDIRECT_URI=https://mis.example.com/sso/callback/   (optional)
    SSO_ALLOWED_DOMAINS=infisetu.com                          (optional, comma list)

Development without a Microsoft tenant:

    SSO_ENABLED=True
    SSO_DEV_MOCK=True        (only honoured while DEBUG=True)
"""

from django.conf import settings

MOCK_TENANT = "dev-tenant"
MOCK_CLIENT_ID = "dev-client"
MOCK_CLIENT_SECRET = "dev-secret"


def enabled():
    return bool(getattr(settings, "SSO_ENABLED", False))


def mock_enabled():
    return bool(settings.DEBUG and getattr(settings, "SSO_DEV_MOCK", False))


def base_url(request):
    return request.build_absolute_uri("/").rstrip("/")


def tenant():
    if mock_enabled():
        return MOCK_TENANT
    return getattr(settings, "ENTRA_TENANT_ID", "") or "organizations"


def client_id():
    return MOCK_CLIENT_ID if mock_enabled() else getattr(settings, "ENTRA_CLIENT_ID", "")


def client_secret():
    return (
        MOCK_CLIENT_SECRET if mock_enabled() else getattr(settings, "ENTRA_CLIENT_SECRET", "")
    )


def authority(request):
    if mock_enabled():
        return f"{base_url(request)}/dev-idp/{MOCK_TENANT}"
    override = getattr(settings, "SSO_AUTHORITY", "")
    return (override or f"https://login.microsoftonline.com/{tenant()}").rstrip("/")


def redirect_uri(request):
    return getattr(settings, "SSO_REDIRECT_URI", "") or f"{base_url(request)}/sso/callback/"


def endpoints(request):
    base = authority(request)
    return {
        "authorize": f"{base}/oauth2/v2.0/authorize",
        "token": f"{base}/oauth2/v2.0/token",
        "keys": f"{base}/discovery/v2.0/keys",
        "issuer": f"{base}/v2.0",
    }


def allowed_domains():
    raw = getattr(settings, "SSO_ALLOWED_DOMAINS", "") or ""
    if isinstance(raw, str):
        raw = raw.split(",")
    return [d.strip().lower().lstrip("@") for d in raw if d.strip()]
