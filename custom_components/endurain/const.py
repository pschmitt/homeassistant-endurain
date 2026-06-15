"""Constants for the Endurain integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "endurain"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.EVENT, Platform.CAMERA]

CONF_MFA_CODE = "mfa_code"
CONF_ENABLE_GEARS = "enable_gears"
CONF_ENABLE_GOALS = "enable_goals"
CONF_ENABLE_HEALTH = "enable_health"
CONF_ENABLE_LIFETIME = "enable_lifetime"

DEFAULT_TITLE = "Endurain"
DEFAULT_URL = "https://endurain.brkn.lol"
DEFAULT_SCAN_INTERVAL = 4 * 60 * 60
MIN_SCAN_INTERVAL = 15 * 60

DEFAULT_ENABLE_GEARS = True
DEFAULT_ENABLE_GOALS = True
DEFAULT_ENABLE_HEALTH = True
DEFAULT_ENABLE_LIFETIME = True

SERVICE_REFRESH_ACTIVITIES = "refresh_activities"
SERVICE_SYNC_RECENT_STRAVA = "sync_recent_strava"
SERVICE_SYNC_STRAVA_GEAR = "sync_strava_gear"
SERVICE_BULK_IMPORT = "bulk_import"
SERVICE_IMPORT_STRAVA_SHOES = "import_strava_shoes"
SERVICE_IMPORT_STRAVA_BIKES = "import_strava_bikes"

ATTR_ACTIVITY_COUNT = "activity_count"
ATTR_TOTAL_CALORIES = "total_calories"
ATTR_TOTAL_DISTANCE_KM = "total_distance_km"
ATTR_TOTAL_DURATION_HOURS = "total_duration_hours"
ATTR_TOTAL_ELEVATION_GAIN_M = "total_elevation_gain_m"
ATTR_BREAKDOWN = "breakdown"
ATTR_TYPE_BREAKDOWN = "type_breakdown"
