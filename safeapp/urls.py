from django.urls import path

from .views import (
    HazardListView,
    ShelterListView,
    generate_alert_message,
    recommend_route,
    send_sms_notification,
    simulate_disaster,
)

urlpatterns = [
    path("hazards/", HazardListView.as_view(), name="hazard-list"),
    path("shelters/", ShelterListView.as_view(), name="shelter-list"),
    path("simulate/", simulate_disaster, name="simulate-disaster"),
    path("route/recommend/", recommend_route, name="recommend-route"),
    path("alert/generate/", generate_alert_message, name="generate-alert"),
    path("alert/sms/", send_sms_notification, name="send-sms"),
]
