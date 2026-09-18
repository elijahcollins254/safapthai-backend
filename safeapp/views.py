import math
import re
from typing import Any

import africastalking
import openai
import requests
from django.conf import settings
from django.db.models import QuerySet
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import generics
from rest_framework.parsers import JSONParser

from .models import Hazard, MapPerson, MapZone, Shelter
from .serializers import HazardSerializer, MapPersonSerializer, MapZoneSerializer, ShelterSerializer, point_in_polygon


def normalize_phone_number(phone: str) -> str | None:
    normalized = re.sub(r"[\s()-]", "", phone)
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    elif normalized.startswith("254"):
        normalized = f"+{normalized}"
    elif normalized.startswith("07") or normalized.startswith("01"):
        normalized = f"+254{normalized[1:]}"
    return normalized if re.fullmatch(r"\+[1-9]\d{7,14}", normalized) else None


class HazardListView(generics.ListAPIView):
    queryset = Hazard.objects.all()
    serializer_class = HazardSerializer


class ShelterListView(generics.ListAPIView):
    queryset = Shelter.objects.all()
    serializer_class = ShelterSerializer


@method_decorator(csrf_exempt, name="dispatch")
class MapPersonListCreateView(generics.ListCreateAPIView):
    queryset = MapPerson.objects.order_by("-created_at")
    serializer_class = MapPersonSerializer


@method_decorator(csrf_exempt, name="dispatch")
class MapZoneListCreateView(generics.ListCreateAPIView):
    queryset = MapZone.objects.order_by("-created_at")
    serializer_class = MapZoneSerializer


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


def route_intersects_zone(route_points: list[tuple[float, float]], zone: MapZone) -> bool:
    return any(
        point_in_polygon(latitude, longitude, zone.coordinates)
        for latitude, longitude in route_points
    )


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
    if not polyline:
        return []

    points = []
    latitude = 0
    longitude = 0
    index = 0
    while index < len(polyline):
        coordinates = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(polyline):
                    return points
                byte = ord(polyline[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            value = ~(result >> 1) if result & 1 else result >> 1
            coordinates.append(value)
        latitude += coordinates[0]
        longitude += coordinates[1]
        points.append((latitude / 100000, longitude / 100000))
    return points


def build_route_payload(route_response: dict[str, Any], origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
    legs = []
    total_distance = 0
    total_duration = 0
    overview_polyline = ""

    if route_response.get("routes"):
        first_route = route_response["routes"][0]
        total_distance = first_route.get("distanceMeters", 0)
        duration = first_route.get("duration", "0s")
        total_duration = int(float(str(duration).removesuffix("s")))
        overview_polyline = first_route.get("polyline", {}).get("encodedPolyline", "")
        legs = [
            {
                "distance_meters": first_route.get("distanceMeters", 0),
                "duration_seconds": total_duration,
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


def get_google_route(origin: tuple[float, float], destination: tuple[float, float], travel_mode: str = "DRIVE") -> dict[str, Any]:
    key = settings.GOOGLE_MAPS_API_KEY
    if not key:
        return {}

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    body: dict[str, Any] = {
        "origin": {
            "location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}},
        },
        "destination": {
            "location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}},
        },
        "travelMode": travel_mode,
    }
    if travel_mode in {"DRIVE", "BICYCLE", "TWO_WHEELER"}:
        body["computeAlternativeRoutes"] = True
    if travel_mode == "DRIVE":
        body["routeModifiers"] = {"avoidTolls": True}

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
    }

    response = requests.post(url, headers=headers, json=body, timeout=15)
    if response.status_code != 200:
        return {}

    return response.json()


def hazard_exit_candidates(origin: tuple[float, float], coordinates: list[dict[str, float]]) -> list[tuple[float, float]]:
    if len(coordinates) < 3:
        return []

    center_latitude = sum(point["lat"] for point in coordinates) / len(coordinates)
    center_longitude = sum(point["lng"] for point in coordinates) / len(coordinates)
    longitude_scale = max(math.cos(math.radians(center_latitude)), 0.1)
    candidates = []

    for index, current in enumerate(coordinates):
        previous = coordinates[index - 1]
        segment_latitude = current["lat"] - previous["lat"]
        segment_longitude = (current["lng"] - previous["lng"]) * longitude_scale
        segment_length = math.hypot(segment_latitude, segment_longitude)
        if not segment_length:
            continue

        origin_latitude = origin[0] - previous["lat"]
        origin_longitude = (origin[1] - previous["lng"]) * longitude_scale
        fraction = max(0, min(1, (origin_latitude * segment_latitude + origin_longitude * segment_longitude) / (segment_length ** 2)))
        boundary_latitude = previous["lat"] + fraction * segment_latitude
        boundary_longitude = previous["lng"] + fraction * (current["lng"] - previous["lng"])
        outward_latitude = boundary_latitude - center_latitude
        outward_longitude = boundary_longitude - center_longitude
        outward_length = math.hypot(outward_latitude, outward_longitude) or 1
        candidates.append((boundary_latitude + outward_latitude / outward_length * 0.00025, boundary_longitude + outward_longitude / outward_length * 0.00025))

    return candidates


@csrf_exempt
@require_http_methods(["POST"])
def recommend_exit_route(request):
    data = JSONParser().parse(request)
    user_lat = data.get("latitude")
    user_lng = data.get("longitude")
    hazard_zone = data.get("hazard_zone")

    if user_lat is None or user_lng is None or not isinstance(hazard_zone, list):
        return JsonResponse({"error": "latitude, longitude, and hazard_zone are required"}, status=400)

    origin = (float(user_lat), float(user_lng))
    candidates = hazard_exit_candidates(origin, hazard_zone)
    routes = []
    for destination in candidates:
        route_response = get_google_route(origin, destination)
        payload = build_route_payload(route_response, origin, destination)
        if payload["distance_meters"]:
            routes.append({**payload, "destination": {"latitude": destination[0], "longitude": destination[1]}})

    if not routes:
        return JsonResponse({"message": "No exit route found", "route": None})

    shortest_route = min(routes, key=lambda route: route["distance_meters"])
    return JsonResponse({"route": shortest_route})


def simplify_route(route_response: dict[str, Any], hazards: list[Hazard], hazard_zones: list[MapZone], shelter: Shelter, origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
    payload = build_route_payload(route_response, origin, destination)
    hazard_names = []
    route_points = []

    if route_response.get("routes"):
        overview_polyline = route_response["routes"][0].get("polyline", {}).get("encodedPolyline")
        route_points = sample_points_from_polyline(overview_polyline)

    if not route_points:
        route_points = [origin, destination]

    unsafe = False
    for hazard in hazards:
        if route_intersects_hazard(route_points, hazard) or segment_intersects_hazard(origin, destination, hazard):
            hazard_names.append(hazard.name)
            unsafe = True

    for zone in hazard_zones:
        if route_intersects_zone(route_points, zone):
            hazard_names.append(zone.name)
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


def generate_route_sms(person: MapPerson, source_zone: MapZone, destination_zone: MapZone, route: dict[str, Any], warnings: list[str]) -> str:
    travel_minutes = max(1, round(route["duration_seconds"] / 60))
    distance_km = route["distance_meters"] / 1000
    warning_text = ", ".join(warnings) if warnings else "no active hazard areas"
    fallback = (
        f"SAFEPATH ALERT, {person.name}: Please leave {source_zone.name} and go to {destination_zone.name}. "
        f"Route: {distance_km:.1f} km, about {travel_minutes} minutes. Avoid: {warning_text}. "
        "Follow official instructions and call local emergency services if you are in immediate danger."
    )

    if not settings.OPENAI_API_KEY:
        return fallback

    try:
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            max_tokens=180,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write one concise emergency SMS in plain text. Use the supplied facts only; never invent a street, ETA, "
                        "distance, or hazard. Address the recipient by name. Include the destination, route distance, estimated minutes, and an explicit "
                        "Avoid list. Use natural capitalization, commas, full stops, and one exclamation mark only if it improves urgency. "
                        "Do not use markdown, emojis, headings, or a sign-off. Keep it under 480 characters."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Recipient: {person.name}\n"
                        f"Current area: {source_zone.name}\n"
                        f"Destination: {destination_zone.name}\n"
                        f"Route distance: {distance_km:.1f} km\n"
                        f"Estimated travel time: {travel_minutes} minutes\n"
                        f"Places or hazards to avoid: {warning_text}\n"
                        "Write the SMS now."
                    ),
                },
            ],
        )
        message = response.choices[0].message.content.strip()
        required_facts = [destination_zone.name, str(travel_minutes), "Avoid"]
        if message and all(fact.lower() in message.lower() for fact in required_facts):
            return message[:480]
        return fallback
    except Exception:
        return fallback


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
    travel_mode = str(data.get("travel_mode", "DRIVE")).upper()
    if travel_mode == "BIKE":
        travel_mode = "BICYCLE"

    if user_lat is None or user_lng is None or travel_mode not in {"DRIVE", "WALK", "BICYCLE"}:
        return JsonResponse({"error": "latitude and longitude are required"}, status=400)

    shelters = Shelter.objects.filter(status="open")
    hazards = list(Hazard.objects.filter(status="active"))
    hazard_zones = list(MapZone.objects.filter(zone_type="hazard"))
    recommendations = []

    origin = (float(user_lat), float(user_lng))
    for shelter in shelters:
        destination = (shelter.latitude, shelter.longitude)
        route_response = get_google_route(origin, destination, travel_mode)
        route_options = route_response.get("routes", [])
        for route_option in route_options or [{}]:
            route_data = simplify_route({"routes": [route_option]} if route_option else {}, hazards, hazard_zones, shelter, origin, destination)
            if not route_data["unsafe"]:
                recommendations.append(route_data)
                break

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
        normalized = normalize_phone_number(recipient)
        if normalized:
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
            send_options["sender_id"] = settings.AFRICASTALKING_SENDER_ID
        result = sms.send(**send_options)
        return JsonResponse({"success": True, "recipients": normalized_recipients, "result": result})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


def zone_centroid(coordinates: list[dict[str, float]]) -> tuple[float, float] | None:
    if not coordinates:
        return None
    return (
        sum(float(point["lat"]) for point in coordinates) / len(coordinates),
        sum(float(point["lng"]) for point in coordinates) / len(coordinates),
    )


@csrf_exempt
@require_http_methods(["POST"])
def send_zone_route_sms(request):
    data = JSONParser().parse(request)
    zone_id = data.get("zone_id")
    if zone_id is None:
        return JsonResponse({"error": "zone_id is required"}, status=400)

    try:
        source_zone = MapZone.objects.get(id=zone_id)
    except (MapZone.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "zone was not found"}, status=404)

    safe_zones = [
        zone for zone in MapZone.objects.filter(zone_type="safe")
        if zone_centroid(zone.coordinates)
    ]
    if not safe_zones:
        return JsonResponse({"error": "no safe zones are configured"}, status=400)

    people = [
        person for person in MapPerson.objects.all()
        if point_in_polygon(person.latitude, person.longitude, source_zone.coordinates)
    ]
    if not people:
        return JsonResponse({"success": True, "zone": source_zone.name, "sent": [], "skipped": []})

    if not settings.AFRICASTALKING_USERNAME or not settings.AFRICASTALKING_API_KEY:
        return JsonResponse(
            {"success": False, "message": "Africa's Talking is not configured"},
            status=503,
        )

    active_hazards = list(Hazard.objects.filter(status="active"))
    hazard_zones = list(MapZone.objects.filter(zone_type="hazard"))
    africastalking.initialize(
        username=settings.AFRICASTALKING_USERNAME,
        api_key=settings.AFRICASTALKING_API_KEY,
    )
    sms = africastalking.SMS
    sent = []
    skipped = []

    for person in people:
        if not person.phone:
            skipped.append({"person": person.name, "reason": "no phone number"})
            continue
        phone_number = normalize_phone_number(person.phone)
        if not phone_number:
            skipped.append({"person": person.name, "reason": f"invalid phone number: {person.phone}"})
            continue

        origin = (person.latitude, person.longitude)
        route_options = []
        for safe_zone in safe_zones:
            destination = zone_centroid(safe_zone.coordinates)
            if destination is None:
                continue
            route_response = get_google_route(origin, destination)
            for route_option in route_response.get("routes", []) or [{}]:
                route = build_route_payload({"routes": [route_option]} if route_option else {}, origin, destination)
                route_points = sample_points_from_polyline(route["polyline"])
                if not route_points:
                    route_points = [origin, destination]
                warnings = [
                    hazard.name for hazard in active_hazards
                    if route_intersects_hazard(route_points, hazard)
                    or segment_intersects_hazard(origin, destination, hazard)
                ]
                warnings.extend(
                    zone.name for zone in hazard_zones
                    if route_intersects_zone(route_points, zone)
                )
                avoid_names = [hazard.name for hazard in active_hazards]
                avoid_names.extend(zone.name for zone in hazard_zones)
                route_options.append((bool(warnings), route["duration_seconds"], route, safe_zone, avoid_names))

        if not route_options:
            skipped.append({"person": person.name, "reason": "no safe route found"})
            continue

        safe_options = [option for option in route_options if not option[0]]
        if not safe_options:
            skipped.append({"person": person.name, "reason": "no safe route found"})
            continue

        _, _, route, destination_zone, warnings = min(safe_options, key=lambda option: option[1])
        message = generate_route_sms(person, source_zone, destination_zone, route, warnings)
        try:
            send_options = {"message": message, "recipients": [phone_number]}
            if settings.AFRICASTALKING_SENDER_ID:
                send_options["sender_id"] = settings.AFRICASTALKING_SENDER_ID
            sms.send(**send_options)
            sent.append({"person": person.name, "phone": phone_number, "zone": destination_zone.name, "message": message})
        except Exception as exc:
            skipped.append({"person": person.name, "reason": str(exc)})

    return JsonResponse({"success": True, "zone": source_zone.name, "sent": sent, "skipped": skipped})
