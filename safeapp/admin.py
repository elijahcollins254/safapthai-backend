from django.contrib import admin

from .models import Hazard, Incident, MapPerson, MapZone, Shelter


@admin.register(Hazard)
class HazardAdmin(admin.ModelAdmin):
    list_display = ("name", "hazard_type", "severity", "status", "radius")
    list_filter = ("hazard_type", "severity", "status")


@admin.register(Shelter)
class ShelterAdmin(admin.ModelAdmin):
    list_display = ("name", "latitude", "longitude", "capacity", "current_occupancy", "status")
    list_filter = ("status",)


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("incident_type", "severity", "status", "created_at")
    list_filter = ("incident_type", "severity", "status")


@admin.register(MapPerson)
class MapPersonAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "status", "latitude", "longitude", "created_at")
    list_filter = ("status",)


@admin.register(MapZone)
class MapZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "zone_type", "created_at")
    list_filter = ("zone_type",)
