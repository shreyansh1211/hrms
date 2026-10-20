"""
OpenID Connect authorization-code flow with PKCE for Microsoft Entra ID.

The ID token is verified here (signature via the provider's JWKS, issuer,
audience, expiry, nonce and tenant); nothing from the callback is trusted
before that. Users are never created automatically: the Microsoft account's
e-mail must match an existing employee.
"""

import base64
import hashlib
import json
import secrets
from urllib.parse import urlencode

import jwt
import requests
from django.db.models import Q
from jwt.algorithms import RSAAlgorithm

from microsoft_sso import conf

TIMEOUT = 10
SESSION_KEY = "sso_flow"


class SsoError(Exception):
    """A sign-in failure that is safe to show to the user."""


# Thin wrappers so tests can route HTTP to the in-process dev provider.
def http_post(url, data):
    return requests.post(url, data=data, timeout=TIMEOUT)


def http_get(url):
    return requests.get(url, timeout=TIMEOUT)


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def start(request, next_url=""):
    """Return the provider URL to send the browser to."""
    verifier = secrets.token_urlsafe(64)
    flow = {
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": verifier,
        "next": next_url,
    }
    request.session[SESSION_KEY] = flow
    params = {
        "client_id": conf.client_id(),
        "response_type": "code",
        "redirect_uri": conf.redirect_uri(request),
        "response_mode": "query",
        "scope": "openid profile email",
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{conf.endpoints(request)['authorize']}?{urlencode(params)}"


def _verify_id_token(request, id_token, nonce):
    endpoints = conf.endpoints(request)
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
        keys = http_get(endpoints["keys"]).json().get("keys", [])
    except Exception as exc:
        raise SsoError("Could not verify the sign-in response.") from exc
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if jwk is None:
        raise SsoError("The sign-in response was signed with an unknown key.")
    tenant = conf.tenant()
    multi_tenant = tenant in ("common", "organizations", "consumers")
    try:
        claims = jwt.decode(
            id_token,
            key=RSAAlgorithm.from_jwk(json.dumps(jwk)),
            algorithms=["RS256"],
            audience=conf.client_id(),
            issuer=None if multi_tenant else endpoints["issuer"],
            leeway=60,
            options={
                "require": ["exp", "iat", "aud", "iss"],
                "verify_iss": not multi_tenant,
            },
        )
    except jwt.PyJWTError as exc:
        raise SsoError("The sign-in response was not valid.") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoError("The sign-in response did not match this request.")
    if not multi_tenant and claims.get("tid") and claims["tid"] != tenant:
        raise SsoError("This account belongs to a different organisation.")
    return claims


def finish(request):
    """Validate the callback and return the verified ID-token claims."""
    flow = request.session.pop(SESSION_KEY, None)
    if not flow:
        raise SsoError("Your sign-in session expired. Please try again.")
    if request.GET.get("error"):
        raise SsoError(
            "Microsoft sign-in was cancelled or refused. "
            + (request.GET.get("error_description", "")[:200])
        )
    state = request.GET.get("state", "")
    if not secrets.compare_digest(state, flow["state"]):
        raise SsoError("The sign-in response did not match this request.")
    code = request.GET.get("code")
    if not code:
        raise SsoError("No authorisation code was returned.")
    try:
        response = http_post(
            conf.endpoints(request)["token"],
            {
                "client_id": conf.client_id(),
                "client_secret": conf.client_secret(),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": conf.redirect_uri(request),
                "code_verifier": flow["verifier"],
            },
        )
        payload = response.json()
    except Exception as exc:
        raise SsoError("Could not reach Microsoft to complete sign-in.") from exc
    id_token = payload.get("id_token")
    if response.status_code != 200 or not id_token:
        raise SsoError("Microsoft did not accept the sign-in request.")
    claims = _verify_id_token(request, id_token, flow["nonce"])
    claims["_next"] = flow.get("next", "")
    return claims


def email_from_claims(claims):
    value = claims.get("email") or claims.get("preferred_username") or claims.get("upn") or ""
    return value.strip().lower()


def find_user(email):
    """The active user whose employee record carries this e-mail, else raise."""
    from employee.models import Employee

    if not email or "@" not in email:
        raise SsoError("Microsoft did not return an e-mail address for this account.")
    domains = conf.allowed_domains()
    if domains and email.rsplit("@", 1)[1] not in domains:
        raise SsoError("This e-mail domain is not allowed to sign in here.")
    employee = (
        Employee.objects.filter(
            Q(email__iexact=email) | Q(employee_work_info__email__iexact=email)
        )
        .select_related("employee_user_id")
        .first()
    )
    user = employee.employee_user_id if employee else None
    if user is None or not user.is_active or not employee.is_active:
        raise SsoError(
            f"No active Infisetu MIS account matches {email}. "
            "Ask HR to add this e-mail to your employee profile."
        )
    return user
