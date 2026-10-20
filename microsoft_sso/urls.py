from django.urls import path

from microsoft_sso import views

urlpatterns = [
    path("login/", views.sso_login, name="sso-login"),
    path("callback/", views.sso_callback, name="sso-callback"),
]
