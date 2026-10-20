import logging

from django.contrib import messages
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from microsoft_sso import conf, oidc

logger = logging.getLogger(__name__)

AUTH_BACKEND = "base.auth_backends.CompanyScopedBackend"


def sso_login(request):
    """Start the Microsoft sign-in."""
    if not conf.enabled():
        raise Http404
    next_url = request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = ""
    return redirect(oidc.start(request, next_url))


def sso_callback(request):
    """Finish the sign-in: verify the token, match the employee, log them in."""
    if not conf.enabled():
        raise Http404
    try:
        claims = oidc.finish(request)
        user = oidc.find_user(oidc.email_from_claims(claims))
    except oidc.SsoError as exc:
        messages.error(request, str(exc))
        return redirect("/login/")
    except Exception:
        logger.exception("Unexpected SSO failure")
        messages.error(request, "Microsoft sign-in failed. Please try again or use your password.")
        return redirect("/login/")
    # Microsoft owns the password, so the "change your temporary password" step
    # that new local accounts go through does not apply.
    if getattr(user, "is_new_employee", False):
        user.is_new_employee = False
        user.save(update_fields=["is_new_employee"])
    login(request, user, backend=AUTH_BACKEND)
    next_url = claims.get("_next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        return redirect(next_url)
    return redirect("/")
