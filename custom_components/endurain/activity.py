"""Helpers for Endurain activity entities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ACTIVITY_TYPE_NAMES: dict[int, str] = {
    1: "Run",
    2: "Bike",
    3: "Swim",
    4: "Strength",
    5: "Cardio",
    6: "Hike",
    7: "Rowing",
    8: "Snow Ski",
    9: "Snowboard",
    10: "Windsurf",
    11: "Walk",
    12: "Stand Up Paddleboarding",
    13: "Surfing",
    14: "Kayaking",
    15: "Sailing",
    16: "Snowshoeing",
    17: "Inline Skating",
}


def activity_name(activity: Mapping[str, Any]) -> str | None:
    """Return the human-readable activity name."""
    value = activity.get("name")
    return str(value) if value else None


def activity_type_name(activity: Mapping[str, Any]) -> str | None:
    """Return the normalized activity type name."""
    activity_type = activity.get("activity_type")
    if isinstance(activity_type, int):
        return ACTIVITY_TYPE_NAMES.get(activity_type, f"Type {activity_type}")
    return None


def activity_primary_timestamp(activity: Mapping[str, Any]) -> str | None:
    """Return the most useful activity timestamp."""
    for key in (
        "start_time_tz_applied",
        "start_time",
        "created_at_tz_applied",
        "created_at",
    ):
        value = activity.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def activity_distance_km(activity: Mapping[str, Any]) -> float | None:
    """Return the activity distance in kilometers."""
    value = activity.get("distance")
    if isinstance(value, int | float):
        return round(float(value) / 1000, 2)
    return None


def activity_url(base_url: str, activity: Mapping[str, Any]) -> str | None:
    """Return the frontend URL for an activity."""
    activity_id = activity.get("id")
    if not isinstance(activity_id, int):
        return None
    return f"{base_url.rstrip('/')}/activity/{activity_id}"


def activity_duration_seconds(activity: Mapping[str, Any]) -> float | None:
    """Return the best-known duration in seconds."""
    for key in ("total_timer_time", "total_elapsed_time"):
        value = activity.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def activity_extra_attributes(activity: Mapping[str, Any]) -> dict[str, Any]:
    """Return activity attributes enriched with friendly derived fields."""
    attrs = dict(activity)
    attrs["activity_type_name"] = activity_type_name(activity)
    attrs["distance_km"] = activity_distance_km(activity)
    duration = activity_duration_seconds(activity)
    attrs["duration_seconds"] = round(duration, 2) if duration is not None else None
    attrs["duration_hours"] = round(duration / 3600, 2) if duration is not None else None
    attrs["primary_timestamp"] = activity_primary_timestamp(activity)
    if isinstance(activity.get("average_speed"), int | float):
        attrs["average_speed_kmh"] = round(float(activity["average_speed"]) * 3.6, 2)
    if isinstance(activity.get("max_speed"), int | float):
        attrs["max_speed_kmh"] = round(float(activity["max_speed"]) * 3.6, 2)
    if isinstance(activity.get("pace"), int | float) and float(activity["pace"]) > 0:
        # pace is stored as s/m (seconds per metre); convert to min/km
        pace_min_per_km = float(activity["pace"]) * 1000 / 60
        attrs["pace_min_per_km"] = round(pace_min_per_km, 2)
        mins = int(pace_min_per_km)
        secs = int(round((pace_min_per_km - mins) * 60))
        attrs["pace_formatted"] = f"{mins}:{secs:02d} /km"
    location = " ".join(
        str(value) for value in (activity.get("city"), activity.get("town"), activity.get("country")) if value
    )
    attrs["location"] = location or None
    return attrs


def extract_route_points(streams: list[dict[str, Any]] | None) -> list[tuple[float, float]]:
    """Extract latitude/longitude points from activity streams."""
    if not streams:
        return []

    route_points: list[tuple[float, float]] = []
    for stream in streams:
        if not isinstance(stream, Mapping):
            continue
        waypoints = stream.get("stream_waypoints")
        if not isinstance(waypoints, list):
            continue
        current_points: list[tuple[float, float]] = []
        for waypoint in waypoints:
            point = _extract_point(waypoint)
            if point is not None:
                current_points.append(point)
        if len(current_points) > len(route_points):
            route_points = current_points

    return route_points


def extract_lap_route_points(laps: list[dict[str, Any]] | None) -> list[tuple[float, float]]:
    """Extract route points from lap boundaries."""
    if not laps:
        return []

    points: list[tuple[float, float]] = []
    for lap in laps:
        if not isinstance(lap, Mapping):
            continue
        start = _extract_point(lap)
        end = _extract_lap_end_point(lap)
        if start is not None and (not points or points[-1] != start):
            points.append(start)
        if end is not None and (not points or points[-1] != end):
            points.append(end)
    return points


def _extract_point(waypoint: Any) -> tuple[float, float] | None:
    """Extract a route point from a waypoint payload."""
    if not isinstance(waypoint, Mapping):
        return None

    candidates = (
        ("latitude", "longitude"),
        ("lat", "lng"),
        ("lat", "lon"),
        ("start_position_lat", "start_position_long"),
        ("position_lat", "position_long"),
    )
    for lat_key, lon_key in candidates:
        lat = waypoint.get(lat_key)
        lon = waypoint.get(lon_key)
        if isinstance(lat, int | float) and isinstance(lon, int | float):
            return float(lat), float(lon)

    for nested_key in ("point", "position", "location"):
        nested = waypoint.get(nested_key)
        if nested is waypoint:
            continue
        point = _extract_point(nested)
        if point is not None:
            return point

    return None


def _extract_lap_end_point(waypoint: Any) -> tuple[float, float] | None:
    """Extract a lap end point."""
    if not isinstance(waypoint, Mapping):
        return None
    lat = waypoint.get("end_position_lat")
    lon = waypoint.get("end_position_long")
    if isinstance(lat, int | float) and isinstance(lon, int | float):
        return float(lat), float(lon)
    return None
