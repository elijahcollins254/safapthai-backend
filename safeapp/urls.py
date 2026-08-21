from django.urls import path

from .views import (
    HazardListView,
    MapPersonListCreateView,
    MapZoneListCreateView,
    ShelterListView,
    generate_alert_message,
    recommend_route,
    send_sms_notification,
    send_zone_route_sms,
    simulate_disaster,
)

urlpatterns = [
    path("hazards/", HazardListView.as_view(), name="hazard-list"),
    path("shelters/", ShelterListView.as_view(), name="shelter-list"),
    path("people/", MapPersonListCreateView.as_view(), name="map-person-list-create"),
    path("zones/", MapZoneListCreateView.as_view(), name="map-zone-list-create"),
    path("simulate/", simulate_disaster, name="simulate-disaster"),
    path("route/recommend/", recommend_route, name="recommend-route"),
    path("alert/generate/", generate_alert_message, name="generate-alert"),
    path("alert/sms/", send_sms_notification, name="send-sms"),
    path("alert/zone-sms/", send_zone_route_sms, name="send-zone-sms"),
]
