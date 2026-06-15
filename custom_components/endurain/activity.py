"""Helpers for Endurain activity entities."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
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
        attrs["pace_min_per_km"] = round(1000 / float(activity["pace"]) / 60, 2)
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


def build_route_svg(
    *,
    title: str,
    subtitle: str | None,
    points: list[tuple[float, float]],
    width: int = 800,
    height: int = 600,
) -> bytes:
    """Build a simple SVG route preview."""
    bg = "#f6f1e8"
    stroke = "#1f5f5b"
    accent = "#d96c06"
    text = "#1f2933"
    grid = "#dfd8cc"

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}" />',
    ]

    for x in range(80, width, 120):
        lines.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" stroke="{grid}" stroke-width="1" />')
    for y in range(80, height, 120):
        lines.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="{grid}" stroke-width="1" />')

    lines.append(f'<text x="36" y="48" font-size="28" font-family="Arial, sans-serif" fill="{text}">{escape(title)}</text>')
    if subtitle:
        lines.append(
            f'<text x="36" y="78" font-size="18" font-family="Arial, sans-serif" fill="{text}" opacity="0.75">{escape(subtitle)}</text>'
        )

    if len(points) >= 2:
        polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in _scale_points(points, width, height))
        scaled = _scale_points(points, width, height)
        start_x, start_y = scaled[0]
        end_x, end_y = scaled[-1]
        lines.append(
            f'<polyline points="{polyline}" fill="none" stroke="{stroke}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" />'
        )
        lines.append(f'<circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="11" fill="{accent}" />')
        lines.append(f'<circle cx="{end_x:.2f}" cy="{end_y:.2f}" r="11" fill="{stroke}" />')
    else:
        lines.append(
            f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" font-size="22" font-family="Arial, sans-serif" fill="{text}" opacity="0.65">No route data available</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines).encode("utf-8")


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


def _scale_points(
    points: list[tuple[float, float]],
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    """Scale GPS points into the SVG viewport."""
    margin_x = width * 0.08
    margin_y = height * 0.12
    xs = [point[1] for point in points]
    ys = [point[0] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    scale = min((width - 2 * margin_x) / span_x, (height - 2 * margin_y) / span_y)
    offset_x = (width - span_x * scale) / 2
    offset_y = (height - span_y * scale) / 2

    scaled: list[tuple[float, float]] = []
    for lat, lon in points:
        x = (lon - min_x) * scale + offset_x
        y = height - ((lat - min_y) * scale + offset_y)
        scaled.append((x, y))
    return scaled
