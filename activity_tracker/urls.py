from django.urls import path

from activity_tracker import api_views, views

urlpatterns = [
    # Employee-facing (dashboard panel)
    path("my-time/", views.my_time, name="activity-my-time"),

    # Admin / manager views
    path("team/", views.team, name="activity-team"),
    path("team/sync/", views.sync_now, name="activity-sync-now"),

    # Employee Track admin page
    path("employee-track/", views.employee_track, name="activity-employee-track"),
    path(
        "employee-track/<int:employee_pk>/",
        views.employee_track_detail,
        name="activity-employee-track-detail",
    ),

    # Desktop agent API
    path("agent/login/", api_views.agent_login, name="agent-login"),
    path("agent/segments/", api_views.agent_segments, name="agent-segments"),
    path("agent/screenshot/", api_views.agent_screenshot, name="agent-screenshot"),
    path("agent/app-usage/", api_views.agent_app_usage, name="agent-app-usage"),
    path("agent/browser-tabs/", api_views.agent_browser_tabs, name="agent-browser-tabs"),
    path("agent/policy/", api_views.agent_policy, name="agent-policy"),
]
