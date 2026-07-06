from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("register/", views.register, name="register"),
    path("login/", views.HemoLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),

    path("dashboard/", views.dashboard, name="dashboard"),

    path("inventory/", views.inventory, name="inventory"),
    path("inventory/import/", views.import_units, name="import_units"),
    path("inventory/import/template/", views.import_template, name="import_template"),
    path("inventory/<int:pk>/discard/", views.discard_unit, name="discard_unit"),
    path("inventory/<int:pk>/broadcast/", views.broadcast_unit, name="broadcast_unit"),

    path("network/", views.network, name="network"),
    path("network/<int:pk>/claim/", views.claim_alert, name="claim_alert"),

    path("profile/", views.profile, name="profile"),

    path("oversight/", views.oversight, name="oversight"),

    path("api/alerts/count/", views.alerts_count, name="alerts_count"),
    path("api/cron/expire/", views.cron_expire, name="cron_expire"),
]