"""Camera platform for Endurain."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Callable
from io import BytesIO
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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

# OSM tile constants — keep requests polite and cache aggressively
_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TILE_SIZE = 256
_TILE_CACHE_MAX = 256
_MAX_TILES_PER_SIDE = 4  # cap tile grid to 4×4 per dimension (+ 1-tile border = 6×6 max)
_MIN_ZOOM = 3
_MAX_ZOOM = 17
_OSM_USER_AGENT = (
    "homeassistant-endurain/1.0 (+https://github.com/pschmitt/homeassistant-endurain)"
)
_OSM_ATTRIBUTION = "© OpenStreetMap contributors"

_tile_cache: OrderedDict[tuple[int, int, int], bytes] = OrderedDict()
_osm_sem: asyncio.Semaphore | None = None


def _osm_semaphore() -> asyncio.Semaphore:
    global _osm_sem
    if _osm_sem is None:
        _osm_sem = asyncio.Semaphore(2)
    return _osm_sem


# --- Slippy-map tile math (Web Mercator / EPSG:3857) ---

def _lon_to_tile_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * (2 ** zoom)


def _lat_to_tile_y(lat: float, zoom: int) -> float:
    lat_r = math.radians(max(-85.0, min(85.0, lat)))
    return (
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
        / 2.0
        * (2 ** zoom)
    )


def _pick_zoom(points: list[tuple[float, float]]) -> int:
    """Return the highest zoom that fits the route in MAX_TILES_PER_SIDE tiles per axis."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    for zoom in range(_MAX_ZOOM, _MIN_ZOOM - 1, -1):
        x_span = int(_lon_to_tile_x(max(lons), zoom)) - int(_lon_to_tile_x(min(lons), zoom)) + 1
        y_span = int(_lat_to_tile_y(min(lats), zoom)) - int(_lat_to_tile_y(max(lats), zoom)) + 1
        if x_span <= _MAX_TILES_PER_SIDE and y_span <= _MAX_TILES_PER_SIDE:
            return zoom
    return _MIN_ZOOM


# --- Tile fetching ---

async def _fetch_tile(session, z: int, x: int, y: int) -> bytes | None:
    """Fetch one OSM tile, serving from in-memory LRU cache when available."""
    key = (z, x, y)
    if key in _tile_cache:
        _tile_cache.move_to_end(key)
        return _tile_cache[key]
    try:
        async with _osm_semaphore():
            async with asyncio.timeout(10):
                async with session.get(
                    _TILE_URL.format(z=z, x=x, y=y),
                    headers={"User-Agent": _OSM_USER_AGENT},
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
    except Exception:
        return None
    _tile_cache[key] = data
    while len(_tile_cache) > _TILE_CACHE_MAX:
        _tile_cache.popitem(last=False)
    return data


async def _build_osm_background(
    session,
    points: list[tuple[float, float]],
    width: int,
    height: int,
) -> tuple[Image.Image, Callable[[float, float], tuple[float, float]]] | None:
    """
    Download the OSM tiles that cover the route, stitch them, and scale to
    (width, height).  Returns (image, project_fn) where project_fn maps
    (lat, lon) to pixel coordinates on the returned image, or None if tiles
    cannot be loaded.
    """
    zoom = _pick_zoom(points)
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    n = 2 ** zoom

    # Tile grid that covers the route bounding box, padded by 1 tile on each side
    x_min = max(0, int(_lon_to_tile_x(min(lons), zoom)) - 1)
    x_max = min(n - 1, int(_lon_to_tile_x(max(lons), zoom)) + 1)
    y_min = max(0, int(_lat_to_tile_y(max(lats), zoom)) - 1)
    y_max = min(n - 1, int(_lat_to_tile_y(min(lats), zoom)) + 1)

    coords = [(x, y) for y in range(y_min, y_max + 1) for x in range(x_min, x_max + 1)]
    raw_tiles = await asyncio.gather(*[_fetch_tile(session, zoom, x, y) for x, y in coords])

    cols = x_max - x_min + 1
    rows = y_max - y_min + 1
    canvas_w = cols * _TILE_SIZE
    canvas_h = rows * _TILE_SIZE
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#e0e0e0")

    loaded = 0
    for (x, y), raw in zip(coords, raw_tiles):
        if raw is None:
            continue
        try:
            tile = Image.open(BytesIO(raw)).convert("RGB")
            canvas.paste(tile, ((x - x_min) * _TILE_SIZE, (y - y_min) * _TILE_SIZE))
            loaded += 1
        except Exception:
            pass

    if loaded == 0:
        return None

    # Scale stitched canvas to target dimensions (letterbox if aspect ratio differs)
    scale = min(width / canvas_w, height / canvas_h)
    new_w = int(canvas_w * scale)
    new_h = int(canvas_h * scale)
    scaled_canvas = canvas.resize((new_w, new_h), Image.LANCZOS)

    bg = Image.new("RGB", (width, height), "#e0e0e0")
    off_x = (width - new_w) // 2
    off_y = (height - new_h) // 2
    bg.paste(scaled_canvas, (off_x, off_y))

    def project(lat: float, lon: float) -> tuple[float, float]:
        tx = _lon_to_tile_x(lon, zoom)
        ty = _lat_to_tile_y(lat, zoom)
        px = (tx - x_min) * _TILE_SIZE * scale + off_x
        py = (ty - y_min) * _TILE_SIZE * scale + off_y
        return px, py

    return bg, project


# --- HA platform wiring ---

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
        """Register the entity with both base classes."""
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

        out_w = width or 800
        out_h = height or 600

        map_result = None
        try:
            session = async_get_clientsession(self.hass)
            map_result = await _build_osm_background(session, points, out_w, out_h)
        except Exception:
            pass

        return _build_route_jpeg(
            title=title,
            subtitle=subtitle,
            points=points,
            width=out_w,
            height=out_h,
            background=map_result[0] if map_result else None,
            project_fn=map_result[1] if map_result else None,
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


# --- Image rendering ---

def _build_route_jpeg(
    *,
    title: str,
    subtitle: str | None,
    points: list[tuple[float, float]],
    width: int,
    height: int,
    background: Image.Image | None = None,
    project_fn: Callable[[float, float], tuple[float, float]] | None = None,
) -> bytes:
    """Render the route as a JPEG.

    When *background* and *project_fn* are supplied (OSM tiles available),
    the route is drawn on top of the real map with a dark header overlay and
    OSM attribution.  Otherwise the original plain grid background is used.
    """
    has_map = background is not None and project_fn is not None
    line_color = "#1f5f5b"
    accent = "#d96c06"

    if has_map:
        image = background.copy()
    else:
        image = Image.new("RGB", (width, height), "#f6f1e8")
        draw_bg = ImageDraw.Draw(image)
        grid_color = "#dfd8cc"
        for x in range(80, width, 120):
            draw_bg.line((x, 0, x, height), fill=grid_color, width=1)
        for y in range(80, height, 120):
            draw_bg.line((0, y, width, y), fill=grid_color, width=1)

    # Semi-transparent header band on map background
    if has_map:
        img_rgba = image.convert("RGBA")
        header = Image.new("RGBA", (width, 68), (20, 30, 40, 200))
        img_rgba.paste(header, (0, 0), header)
        image = img_rgba.convert("RGB")

    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    text_color = "#ffffff" if has_map else "#1f2933"
    title_x, title_y = (16, 16) if has_map else (36, 28)
    sub_x, sub_y = (16, 40) if has_map else (36, 52)
    draw.text((title_x, title_y), title, fill=text_color, font=font)
    if subtitle:
        draw.text((sub_x, sub_y), subtitle, fill=text_color, font=font)

    # Route line
    scaled = (
        [project_fn(lat, lon) for lat, lon in points]
        if project_fn is not None
        else _scale_points(points, width, height)
    )
    if has_map:
        draw.line(scaled, fill="white", width=10, joint="curve")
    draw.line(scaled, fill=line_color, width=6 if has_map else 8, joint="curve")

    # Start (orange) and end (teal) dots
    sx, sy = scaled[0]
    ex, ey = scaled[-1]
    r = 8
    if has_map:
        draw.ellipse((sx - r - 2, sy - r - 2, sx + r + 2, sy + r + 2), fill="white")
        draw.ellipse((ex - r - 2, ey - r - 2, ex + r + 2, ey + r + 2), fill="white")
    draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=accent)
    draw.ellipse((ex - r, ey - r, ex + r, ey + r), fill=line_color)

    if has_map:
        draw.text((4, height - 14), _OSM_ATTRIBUTION, fill="#555555", font=font)

    buf = BytesIO()
    image.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


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
