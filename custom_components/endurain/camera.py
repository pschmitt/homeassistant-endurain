"""Camera platform for Endurain."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from PIL import Image, ImageDraw, ImageFont

from .activity import (
    activity_distance_km,
    activity_name,
    activity_primary_timestamp,
    activity_url,
    extract_lap_route_points,
    extract_route_points,
)
from .const import DOMAIN
from .entity import EndurainEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Endurain camera entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([EndurainLatestWorkoutMapCamera(coordinator, entry)])


class EndurainLatestWorkoutMapCamera(EndurainEntity, Camera):
    """Camera entity exposing a route preview for the latest activity."""

    _attr_icon = "mdi:map-search"
    _attr_name = "Latest Activity Map"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the route camera."""
        super().__init__(coordinator, entry)
        Camera.__init__(self)
        self._attr_unique_id = f"{entry.entry_id}_latest_activity_map"
        self.content_type = "image/jpeg"

    async def async_added_to_hass(self) -> None:
        """Log when the entity is added to Home Assistant."""
        await EndurainEntity.async_added_to_hass(self)
        await Camera.async_added_to_hass(self)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return whether the camera can render an image."""
        activity = self._activity
        if not super().available or activity is None:
            return False
        if activity.get("hide_map"):
            return False
        return len(self._route_points) >= 2

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the current camera image."""
        activity = self._activity
        if activity is None or activity.get("hide_map"):
            return None

        points = self._route_points
        if len(points) < 2:
            return None

        title = activity_name(activity) or "Latest Activity"
        distance_km = activity_distance_km(activity)
        timestamp = activity_primary_timestamp(activity)
        subtitle_parts = []
        if distance_km is not None:
            subtitle_parts.append(f"{distance_km} km")
        if timestamp:
            subtitle_parts.append(timestamp)
        subtitle = " | ".join(subtitle_parts) or None

        return _build_route_jpeg(
            title=title,
            subtitle=subtitle,
            points=points,
            width=width or 800,
            height=height or 600,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose current activity metadata for the map preview."""
        activity = self._activity
        if activity is None:
            return {}
        points = extract_route_points(self._streams)
        return {
            "activity_id": activity.get("id"),
            "activity_name": activity_name(activity),
            "distance_km": activity_distance_km(activity),
            "started_at": activity_primary_timestamp(activity),
            "route_point_count": len(points),
            "map_hidden": bool(activity.get("hide_map")),
            "activity_url": activity_url(self.coordinator.client.base_url, activity),
            "content_type": self.content_type,
        }

    @property
    def _activity(self) -> dict[str, Any] | None:
        """Return the latest activity payload."""
        if not self.coordinator.data:
            return None
        activity = self.coordinator.data.get("latest_activity")
        return activity if isinstance(activity, dict) else None

    @property
    def _streams(self) -> list[dict[str, Any]]:
        """Return the latest activity streams."""
        if not self.coordinator.data:
            return []
        streams = self.coordinator.data.get("latest_activity_streams")
        return streams if isinstance(streams, list) else []

    @property
    def _laps(self) -> list[dict[str, Any]]:
        """Return the latest activity laps."""
        if not self.coordinator.data:
            return []
        laps = self.coordinator.data.get("latest_activity_laps")
        return laps if isinstance(laps, list) else []

    @property
    def _route_points(self) -> list[tuple[float, float]]:
        """Return the best available route points."""
        points = extract_route_points(self._streams)
        if len(points) >= 2:
            return points
        return extract_lap_route_points(self._laps)


def _build_route_jpeg(
    *,
    title: str,
    subtitle: str | None,
    points: list[tuple[float, float]],
    width: int,
    height: int,
) -> bytes:
    """Render the route preview as a JPEG image."""
    background = "#f6f1e8"
    line_color = "#1f5f5b"
    accent = "#d96c06"
    text_color = "#1f2933"
    grid_color = "#dfd8cc"

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    for x in range(80, width, 120):
        draw.line((x, 0, x, height), fill=grid_color, width=1)
    for y in range(80, height, 120):
        draw.line((0, y, width, y), fill=grid_color, width=1)

    draw.text((36, 28), title, fill=text_color, font=font)
    if subtitle:
        draw.text((36, 52), subtitle, fill=text_color, font=font)

    scaled = _scale_points(points, width, height)
    draw.line(scaled, fill=line_color, width=8, joint="curve")
    start_x, start_y = scaled[0]
    end_x, end_y = scaled[-1]
    draw.ellipse((start_x - 8, start_y - 8, start_x + 8, start_y + 8), fill=accent)
    draw.ellipse((end_x - 8, end_y - 8, end_x + 8, end_y + 8), fill=line_color)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _scale_points(
    points: list[tuple[float, float]],
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    """Scale GPS points into the image viewport."""
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
