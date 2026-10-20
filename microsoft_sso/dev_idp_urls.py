from django.urls import path

from microsoft_sso import dev_idp

urlpatterns = [
    path("<str:tenant>/oauth2/v2.0/authorize", dev_idp.authorize),
    path("<str:tenant>/oauth2/v2.0/token", dev_idp.token),
    path("<str:tenant>/discovery/v2.0/keys", dev_idp.keys),
]
