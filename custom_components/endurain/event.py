"""Event platform for Endurain."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .activity import activity_url
from .const import DOMAIN
from .entity import EndurainEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Endurain event entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([EndurainWorkoutUploadedEvent(coordinator, entry)])


class EndurainWorkoutUploadedEvent(EndurainEntity, EventEntity):
    """Fire an event when Endurain sees a new latest workout."""

    _attr_event_types = ["uploaded"]
    _attr_icon = "mdi:upload"
    _attr_name = "Workout Uploaded"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_workout_uploaded"
        self._last_activity_id: int | None = None

    async def async_added_to_hass(self) -> None:
        """Register the coordinator listener."""
        await super().async_added_to_hass()
        current = self._latest_activity
        if current is not None and isinstance(current.get("id"), int):
            self._last_activity_id = current["id"]
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Trigger the event if the latest activity changed."""
        activity = self._latest_activity
        if activity is None:
            self.async_write_ha_state()
            return

        activity_id = activity.get("id")
        if not isinstance(activity_id, int):
            self.async_write_ha_state()
            return

        if self._last_activity_id is None:
            self._last_activity_id = activity_id
        elif activity_id != self._last_activity_id:
            self._last_activity_id = activity_id
            self._trigger_event(
                "uploaded",
                {
                    "activity_id": activity.get("id"),
                    "name": activity.get("name"),
                    "distance_km": round(float(activity.get("distance", 0.0)) / 1000, 2),
                    "start_time": activity.get("start_time_tz_applied")
                    or activity.get("start_time"),
                    "activity_type": activity.get("activity_type"),
                    "gear_id": activity.get("gear_id"),
                    "activity_url": activity_url(self.coordinator.client.base_url, activity),
                },
            )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the latest known workout metadata."""
        activity = self._latest_activity
        if activity is None:
            return {}
        return {
            "latest_activity_id": activity.get("id"),
            "latest_activity_name": activity.get("name"),
            "latest_activity_type": activity.get("activity_type"),
            "latest_activity_start_time": activity.get("start_time_tz_applied")
            or activity.get("start_time"),
            "latest_activity_distance_km": round(float(activity.get("distance", 0.0)) / 1000, 2),
            "latest_activity_gear_id": activity.get("gear_id"),
            "latest_activity_url": activity_url(self.coordinator.client.base_url, activity),
        }

    @property
    def _latest_activity(self) -> dict[str, Any] | None:
        """Return the latest activity payload."""
        if not self.coordinator.data:
            return None
        activity = self.coordinator.data.get("latest_activity")
        return activity if isinstance(activity, dict) else None
