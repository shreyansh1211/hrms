from django.apps import AppConfig
from django.conf import settings


class ActivityTrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "activity_tracker"
    verbose_name = "Active Time"

    def ready(self):
        from django.urls import include, path

        from horilla.urls import urlpatterns

        settings.APPS.append("activity_tracker")
        urlpatterns.append(path("activity/", include("activity_tracker.urls")))
        super().ready()
