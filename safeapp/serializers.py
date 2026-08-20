from rest_framework import serializers

from .models import Hazard, MapPerson, MapZone, Shelter, Incident


class ShelterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shelter
        fields = ["id", "name", "latitude", "longitude", "capacity", "current_occupancy", "status"]


class HazardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hazard
        fields = ["id", "name", "hazard_type", "severity", "latitude", "longitude", "radius", "status"]


class IncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = ["id", "incident_type", "severity", "created_at", "status"]


class MapPersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapPerson
        fields = ["id", "name", "phone", "details", "latitude", "longitude", "status", "created_at"]


class MapZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapZone
        fields = ["id", "name", "zone_type", "details", "coordinates", "created_at"]
