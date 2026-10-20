"""
A tiny stand-in for Microsoft Entra ID, for development only.

Enabled by DEBUG=True together with SSO_DEV_MOCK=True; otherwise every view
returns 404. It speaks the same protocol (authorize / token / JWKS, RS256 ID
tokens, PKCE) so the real sign-in code runs unchanged. The "login" page simply
lets you pick which employee e-mail to sign in as -- there is no password.
"""

import base64
import hashlib
import secrets
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from jwt.algorithms import RSAAlgorithm

from microsoft_sso import conf

_KEY = {}


def _key():
    if "private" not in _KEY:
        _KEY["private"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _KEY["kid"] = secrets.token_hex(8)
    return _KEY["private"], _KEY["kid"]


def _guard():
    if not conf.mock_enabled():
        raise Http404


def authorize(request, tenant):
    _guard()
    params = request.GET if request.method == "GET" else request.POST
    needed = ("client_id", "redirect_uri", "state", "nonce", "code_challenge")
    if any(not params.get(k) for k in needed) or params["client_id"] != conf.MOCK_CLIENT_ID:
        return HttpResponseBadRequest("Invalid authorisation request")
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        if "@" not in email:
            return HttpResponseBadRequest("Enter an e-mail address")
        code = secrets.token_urlsafe(24)
        cache.set(
            f"dev-idp:{code}",
            {
                "email": email,
                "nonce": params["nonce"],
                "challenge": params["code_challenge"],
                "redirect_uri": params["redirect_uri"],
            },
            120,
        )
        sep = "&" if "?" in params["redirect_uri"] else "?"
        return redirect(f"{params['redirect_uri']}{sep}code={code}&state={params['state']}")
    from employee.models import Employee

    emails = list(
        Employee.objects.filter(is_active=True).values_list("email", flat=True)[:30]
    )
    return render(
        request,
        "microsoft_sso/dev_idp_login.html",
        {"emails": emails, "params": {k: params[k] for k in needed}},
    )


@csrf_exempt
def token(request, tenant):
    _guard()
    if request.method != "POST":
        raise Http404
    data = cache.get(f"dev-idp:{request.POST.get('code', '')}")
    cache.delete(f"dev-idp:{request.POST.get('code', '')}")
    bad = JsonResponse({"error": "invalid_grant"}, status=400)
    if (
        not data
        or request.POST.get("client_id") != conf.MOCK_CLIENT_ID
        or request.POST.get("client_secret") != conf.MOCK_CLIENT_SECRET
        or request.POST.get("redirect_uri") != data["redirect_uri"]
    ):
        return bad
    digest = hashlib.sha256(request.POST.get("code_verifier", "").encode()).digest()
    if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != data["challenge"]:
        return bad
    private, kid = _key()
    now = int(time.time())
    id_token = jwt.encode(
        {
            "iss": f"{conf.base_url(request)}/dev-idp/{conf.MOCK_TENANT}/v2.0",
            "aud": conf.MOCK_CLIENT_ID,
            "sub": hashlib.sha1(data["email"].encode()).hexdigest(),
            "tid": conf.MOCK_TENANT,
            "iat": now,
            "exp": now + 600,
            "nonce": data["nonce"],
            "preferred_username": data["email"],
            "email": data["email"],
            "name": data["email"].split("@")[0],
        },
        private,
        algorithm="RS256",
        headers={"kid": kid},
    )
    return JsonResponse({"token_type": "Bearer", "id_token": id_token, "expires_in": 600})


def keys(request, tenant):
    _guard()
    private, kid = _key()
    import json

    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return JsonResponse({"keys": [jwk]})
