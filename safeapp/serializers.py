from rest_framework import serializers

from .models import Hazard, MapPerson, MapZone, Shelter, Incident


def point_in_polygon(latitude: float, longitude: float, coordinates: list[dict[str, float]]) -> bool:
    inside = False
    for index, current in enumerate(coordinates):
        previous = coordinates[index - 1]
        current_lng = current.get("lng")
        previous_lng = previous.get("lng")
        if current_lng == previous_lng:
            continue
        crosses = (current_lng > longitude) != (previous_lng > longitude)
        boundary_latitude = (previous.get("lat") - current.get("lat")) * (longitude - current_lng) / (previous_lng - current_lng) + current.get("lat")
        if crosses and latitude < boundary_latitude:
            inside = not inside
    return inside


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

    def create(self, validated_data):
        person = super().create(validated_data)
        if person.status == "safe" and any(
            zone.zone_type == "hazard" and point_in_polygon(person.latitude, person.longitude, zone.coordinates)
            for zone in MapZone.objects.all()
        ):
            person.status = "at_risk"
            person.save(update_fields=["status"])
        return person


class MapZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapZone
        fields = ["id", "name", "zone_type", "details", "coordinates", "created_at"]

    def create(self, validated_data):
        zone = super().create(validated_data)
        if zone.zone_type == "hazard":
            for person in MapPerson.objects.filter(status="safe"):
                if point_in_polygon(person.latitude, person.longitude, zone.coordinates):
                    person.status = "at_risk"
                    person.save(update_fields=["status"])
        return zone
