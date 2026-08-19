import math
import re
from typing import Any

import africastalking
import openai
import requests
from django.conf import settings
from django.db.models import QuerySet
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import generics
from rest_framework.parsers import JSONParser

from .models import Hazard, Shelter
from .serializers import HazardSerializer, ShelterSerializer


class HazardListView(generics.ListAPIView):
    queryset = Hazard.objects.all()
    serializer_class = HazardSerializer


class ShelterListView(generics.ListAPIView):
    queryset = Shelter.objects.all()
    serializer_class = ShelterSerializer


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def route_intersects_hazard(route_points: list[tuple[float, float]], hazard: Hazard) -> bool:
    for lat, lng in route_points:
        if calculate_distance(lat, lng, hazard.latitude, hazard.longitude) <= hazard.radius:
            return True
    return False


def segment_intersects_hazard(origin: tuple[float, float], destination: tuple[float, float], hazard: Hazard) -> bool:
    (x1, y1), (x2, y2) = origin, destination
    cx, cy = hazard.latitude, hazard.longitude
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return calculate_distance(x1, y1, cx, cy) <= hazard.radius

    t = ((cx - x1) * dx + (cy - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return calculate_distance(closest_x, closest_y, cx, cy) <= hazard.radius


def sample_points_from_polyline(polyline: str) -> list[tuple[float, float]]:
    return []


def build_route_payload(route_response: dict[str, Any], origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
    legs = []
    total_distance = 0
    total_duration = 0
    overview_polyline = ""

    if route_response.get("routes"):
        first_route = route_response["routes"][0]
        total_distance = first_route.get("distanceMeters", 0)
        total_duration = first_route.get("durationSeconds", 0)
        overview_polyline = first_route.get("polyline", {}).get("encodedPolyline", "")
        legs = [
            {
                "distance_meters": first_route.get("distanceMeters", 0),
                "duration_seconds": first_route.get("durationSeconds", 0),
            }
        ]
    else:
        total_distance = calculate_distance(origin[0], origin[1], destination[0], destination[1])
        total_duration = int(total_distance / 500) if total_distance else 0

    return {
        "distance_meters": total_distance,
        "duration_seconds": total_duration,
        "polyline": overview_polyline,
        "legs": legs,
    }


def get_google_route(origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
    key = settings.GOOGLE_MAPS_API_KEY
    if not key:
        return {}

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    body = {
        "origin": {
            "location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}},
        },
        "destination": {
            "location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}},
        },
        "travelMode": "DRIVE",
        "computeAlternativeRoutes": True,
        "routeModifiers": {"avoidTolls": True},
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
    }

    response = requests.post(url, headers=headers, json=body, timeout=15)
    if response.status_code != 200:
        return {}

    return response.json()


def simplify_route(route_response: dict[str, Any], hazard_zones: QuerySet[Hazard], shelter: Shelter, origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
    payload = build_route_payload(route_response, origin, destination)
    hazard_names = []
    route_points = []

    if route_response.get("routes"):
        overview_polyline = route_response["routes"][0].get("polyline", {}).get("encodedPolyline")
        route_points = sample_points_from_polyline(overview_polyline)

    if not route_points:
        route_points = [origin, destination]

    unsafe = False
    for hazard in hazard_zones.filter(status="active"):
        if route_intersects_hazard(route_points, hazard) or segment_intersects_hazard(origin, destination, hazard):
            hazard_names.append(hazard.name)
            unsafe = True

    score = 100
    if unsafe:
        score -= 50
    score -= len(hazard_names) * 10
    score -= payload["distance_meters"] // 1000

    return {
        "shelter_id": shelter.id,
        "shelter_name": shelter.name,
        "distance_meters": payload["distance_meters"],
        "duration_seconds": payload["duration_seconds"],
        "polyline": payload["polyline"],
        "unsafe": unsafe,
        "hazards": hazard_names,
        "safety_score": max(score, 0),
    }


def build_ai_prompt(route_data: dict[str, Any], hazard_zones: list[dict[str, Any]]) -> str:
    hazard_list = ", ".join([hazard["name"] for hazard in hazard_zones]) or "no active hazards"
    travel_minutes = int(route_data["duration_seconds"] / 60)
    travel_km = route_data["distance_meters"] / 1000

    return (
        f"A flood has been detected near the user location. "
        f"The safest route recommendation is to {route_data['shelter_name']} with an estimated distance of {travel_km:.1f} km and ETA {travel_minutes} minutes. "
        f"Active hazards on the path: {hazard_list}. "
        "Generate a concise emergency alert message suitable for SMS and a slightly longer voice prompt. "
        "Use simple language and include the recommended shelter name, estimated travel time, and hazard warning."
    )


@csrf_exempt
@require_http_methods(["POST"])
def simulate_disaster(request):
    data = JSONParser().parse(request)
    description = data.get("description", "Simulated flood")

    Hazard.objects.update(status="cleared")
    new_hazard = Hazard.objects.create(
        name=description,
        hazard_type="flood",
        severity="high",
        latitude=-1.2864,
        longitude=36.8172,
        radius=1200,
        status="active",
    )

    return JsonResponse(
        {
            "success": True,
            "message": "Disaster simulated",
            "hazard": HazardSerializer(new_hazard).data,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def recommend_route(request):
    data = JSONParser().parse(request)
    user_lat = data.get("latitude")
    user_lng = data.get("longitude")

    if user_lat is None or user_lng is None:
        return JsonResponse({"error": "latitude and longitude are required"}, status=400)

    shelters = Shelter.objects.filter(status="open")
    hazards = Hazard.objects.filter(status="active")
    recommendations = []

    origin = (float(user_lat), float(user_lng))
    for shelter in shelters:
        destination = (shelter.latitude, shelter.longitude)
        route_response = get_google_route(origin, destination)
        route_data = simplify_route(route_response, hazards, shelter, origin, destination)
        if not route_data["unsafe"]:
            recommendations.append(route_data)

    recommendations.sort(key=lambda item: (item["unsafe"], -item["safety_score"], item["duration_seconds"]))

    if not recommendations:
        return JsonResponse({"message": "No safe routes found", "routes": []})

    return JsonResponse({"recommended_route": recommendations[0], "routes": recommendations})


@csrf_exempt
@require_http_methods(["POST"])
def generate_alert_message(request):
    data = JSONParser().parse(request)
    route = data.get("route")
    hazards = data.get("hazards", [])

    if not route:
        return JsonResponse({"error": "route data is required"}, status=400)

    if not settings.OPENAI_API_KEY:
        return JsonResponse({"error": "OpenAI API key is not configured"}, status=503)

    openai.api_key = settings.OPENAI_API_KEY
    prompt = build_ai_prompt(route, hazards)

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an emergency alert assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=220,
        )
        content = response.choices[0].message.content.strip()
        return JsonResponse({"message": content})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def send_sms_notification(request):
    data = JSONParser().parse(request)
    message = data.get("message")
    recipients = data.get("recipients")

    if not isinstance(message, str) or not message.strip() or not isinstance(recipients, list) or not recipients:
        return JsonResponse({"error": "message and recipients are required"}, status=400)

    if not settings.AFRICASTALKING_USERNAME or not settings.AFRICASTALKING_API_KEY:
        return JsonResponse(
            {"success": False, "message": "Africa's Talking is not configured"},
            status=503,
        )

    normalized_recipients = []
    for recipient in recipients:
        if not isinstance(recipient, str):
            continue
        normalized = re.sub(r"[\s()-]", "", recipient)
        if re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
            normalized_recipients.append(normalized)

    if not normalized_recipients:
        return JsonResponse(
            {"success": False, "message": "No valid E.164 phone numbers were provided."},
            status=400,
        )

    try:
        africastalking.initialize(
            username=settings.AFRICASTALKING_USERNAME,
            api_key=settings.AFRICASTALKING_API_KEY,
        )
        sms = africastalking.SMS
        send_options = {"message": message.strip(), "recipients": normalized_recipients}
        if settings.AFRICASTALKING_SENDER_ID:
            send_options["from_"] = settings.AFRICASTALKING_SENDER_ID
        result = sms.send(**send_options)
        return JsonResponse({"success": True, "recipients": normalized_recipients, "result": result})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)
