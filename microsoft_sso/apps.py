from django.apps import AppConfig
from django.conf import settings


class MicrosoftSsoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "microsoft_sso"
    verbose_name = "Microsoft Sign-in"

    def ready(self):
        from django.urls import include, path

        from horilla.urls import urlpatterns

        settings.APPS.append("microsoft_sso")
        urlpatterns.append(path("sso/", include("microsoft_sso.urls")))
        # Local stand-in for Microsoft; every view 404s unless DEBUG + SSO_DEV_MOCK.
        urlpatterns.append(path("dev-idp/", include("microsoft_sso.dev_idp_urls")))
        super().ready()
