from django.urls import path

from activity_tracker import views

urlpatterns = [
    path("my-time/", views.my_time, name="activity-my-time"),
    path("team/", views.team, name="activity-team"),
    path("team/sync/", views.sync_now, name="activity-sync-now"),
]
