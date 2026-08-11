from rest_framework import serializers

from .models import Hazard, Shelter, Incident


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
