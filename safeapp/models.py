from django.db import models


class Shelter(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("closed", "Closed"),
    ]

    name = models.CharField(max_length=128)
    latitude = models.FloatField()
    longitude = models.FloatField()
    capacity = models.IntegerField(default=0)
    current_occupancy = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")

    def __str__(self):
        return self.name


class Hazard(models.Model):
    HAZARD_CHOICES = [
        ("flood", "Flood"),
        ("fire", "Fire"),
        ("earthquake", "Earthquake"),
    ]
    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("cleared", "Cleared"),
    ]

    name = models.CharField(max_length=128)
    hazard_type = models.CharField(max_length=24, choices=HAZARD_CHOICES, default="flood")
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default="medium")
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius = models.IntegerField(help_text="Meters")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")

    def __str__(self):
        return self.name


class Incident(models.Model):
    INCIDENT_CHOICES = [
        ("flood", "Flood"),
        ("fire", "Fire"),
        ("earthquake", "Earthquake"),
    ]
    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("resolved", "Resolved"),
    ]

    incident_type = models.CharField(max_length=24, choices=INCIDENT_CHOICES)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="pending")

    def __str__(self):
        return f"{self.incident_type} - {self.severity}"


class MapPerson(models.Model):
    STATUS_CHOICES = [
        ("safe", "Safe"),
        ("at_risk", "At risk"),
    ]

    name = models.CharField(max_length=128)
    phone = models.CharField(max_length=32, blank=True)
    details = models.TextField(blank=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="safe")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class MapZone(models.Model):
    ZONE_CHOICES = [
        ("safe", "Safe"),
        ("at_risk", "At risk"),
        ("hazard", "Hazard"),
    ]

    name = models.CharField(max_length=128)
    zone_type = models.CharField(max_length=16, choices=ZONE_CHOICES)
    details = models.TextField(blank=True)
    coordinates = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
