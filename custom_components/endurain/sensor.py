"""Sensor platform for Endurain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import (
    ATTR_ACTIVITY_COUNT,
    ATTR_BREAKDOWN,
    ATTR_TOTAL_CALORIES,
    ATTR_TOTAL_DISTANCE_KM,
    ATTR_TOTAL_DURATION_HOURS,
    ATTR_TOTAL_ELEVATION_GAIN_M,
    ATTR_TYPE_BREAKDOWN,
    DOMAIN,
)
from .coordinator import EndurainCoordinator
from .entity import EndurainEntity
from .activity import (
    activity_distance_km,
    activity_extra_attributes,
    activity_name,
    activity_primary_timestamp,
    activity_type_name,
    extract_route_points,
)


@dataclass(frozen=True, kw_only=True)
class SummaryDescription(SensorEntityDescription):
    """Description of a summary sensor."""


SUMMARY_SENSORS: tuple[SummaryDescription, ...] = (
    SummaryDescription(
        key="weekly",
        name="Weekly Distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
    ),
    SummaryDescription(
        key="monthly",
        name="Monthly Distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
    ),
    SummaryDescription(
        key="yearly",
        name="Yearly Distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
    ),
    SummaryDescription(
        key="lifetime",
        name="Lifetime Distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Endurain sensors."""
    coordinator: EndurainCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    static_entities: list[SensorEntity] = [
        EndurainSummarySensor(coordinator, entry, description)
        for description in SUMMARY_SENSORS
    ]
    static_entities.extend(
        [
            EndurainLatestWorkoutSensor(coordinator, entry),
            EndurainNotificationsSensor(coordinator, entry),
            EndurainStepsSensor(coordinator, entry),
            EndurainSleepSensor(coordinator, entry),
            EndurainWeightSensor(coordinator, entry),
            EndurainGearCountSensor(coordinator, entry),
        ]
    )
    async_add_entities(static_entities)

    known_dynamic_ids: set[str] = set()

    @callback
    def async_add_dynamic_entities() -> None:
        current_ids: set[str] = set()
        new_entities: list[SensorEntity] = []
        data = coordinator.data or {}

        for goal in data.get("goals", []):
            goal_id = goal.get("goal_id")
            if goal_id is None:
                continue
            unique_id = f"{entry.entry_id}_goal_{goal_id}"
            current_ids.add(unique_id)
            if unique_id in known_dynamic_ids:
                continue
            known_dynamic_ids.add(unique_id)
            new_entities.append(EndurainGoalSensor(coordinator, entry, goal_id))

        for gear in data.get("gear_stats", []):
            gear_id = gear.get("id")
            unique_suffix = gear_id if gear_id is not None else slugify(str(gear.get("nickname", "gear")))
            unique_id = f"{entry.entry_id}_gear_{unique_suffix}"
            current_ids.add(unique_id)
            if unique_id in known_dynamic_ids:
                continue
            known_dynamic_ids.add(unique_id)
            new_entities.append(EndurainGearSensor(coordinator, entry, unique_suffix))

        known_dynamic_ids.intersection_update(current_ids)

        if new_entities:
            async_add_entities(new_entities)

    async_add_dynamic_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_dynamic_entities))


class EndurainSummarySensor(EndurainEntity, SensorEntity):
    """Distance summary sensor."""

    def __init__(
        self,
        coordinator: EndurainCoordinator,
        entry: ConfigEntry,
        description: SummaryDescription,
    ) -> None:
        """Initialize the summary sensor."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}_distance"

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return bool(
            super().available
            and self.coordinator.data
            and self.entity_description.key in self.coordinator.data.get("summaries", {})
        )

    @property
    def native_value(self) -> float | None:
        """Return the summary distance in km."""
        summary = self._summary
        if summary is None:
            return None
        return round(float(summary.get("total_distance", 0.0)) / 1000, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return summary attributes."""
        summary = self._summary
        if summary is None:
            return {}
        return {
            ATTR_TOTAL_DISTANCE_KM: round(float(summary.get("total_distance", 0.0)) / 1000, 2),
            ATTR_TOTAL_DURATION_HOURS: round(float(summary.get("total_duration", 0.0)) / 3600, 2),
            ATTR_TOTAL_ELEVATION_GAIN_M: round(float(summary.get("total_elevation_gain", 0.0)), 2),
            ATTR_ACTIVITY_COUNT: summary.get("activity_count"),
            ATTR_TOTAL_CALORIES: round(float(summary.get("total_calories", 0.0)), 2),
            ATTR_BREAKDOWN: summary.get("breakdown"),
            ATTR_TYPE_BREAKDOWN: [
                {
                    **item,
                    "total_distance_km": round(float(item.get("total_distance", 0.0)) / 1000, 2),
                    "total_duration_hours": round(float(item.get("total_duration", 0.0)) / 3600, 2),
                }
                for item in summary.get("type_breakdown") or []
                if isinstance(item, dict)
            ],
        }

    @property
    def _summary(self) -> dict[str, Any] | None:
        """Return the backing summary object."""
        data = self.coordinator.data or {}
        summaries = data.get("summaries", {})
        summary = summaries.get(self.entity_description.key)
        return summary if isinstance(summary, dict) else None


class EndurainLatestWorkoutSensor(EndurainEntity, SensorEntity):
    """Latest Endurain workout sensor."""

    _attr_icon = "mdi:run-fast"
    _attr_name = "Latest Workout"

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the latest workout sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_latest_workout"

    @property
    def native_value(self) -> str | None:
        """Return the latest workout name."""
        activity = self._activity
        if activity is None:
            return None
        return activity_name(activity) or activity_type_name(activity) or str(activity.get("id"))

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._activity is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the latest workout metadata."""
        activity = self._activity
        if activity is None:
            return {}
        attrs = activity_extra_attributes(activity)
        route_points = extract_route_points(self._streams)
        attrs["has_map"] = len(route_points) >= 2
        attrs["route_point_count"] = len(route_points)
        attrs["map_hidden"] = bool(activity.get("hide_map"))
        attrs["friendly_activity_name"] = activity_name(activity)
        attrs["friendly_activity_type"] = activity_type_name(activity)
        attrs["started_at"] = activity_primary_timestamp(activity)
        attrs["distance_km"] = activity_distance_km(activity)
        return attrs

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


class EndurainNotificationsSensor(EndurainEntity, SensorEntity):
    """Unread Endurain notifications."""

    _attr_icon = "mdi:bell-badge"
    _attr_name = "Unread Notifications"

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the notification sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_notifications"

    @property
    def native_value(self) -> int | None:
        """Return the unread notification count."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("notifications")


class EndurainStepsSensor(EndurainEntity, SensorEntity):
    """Latest steps sensor."""

    _attr_icon = "mdi:shoe-print"
    _attr_name = "Latest Steps"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the steps sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_latest_steps"

    @property
    def native_value(self) -> int | None:
        """Return the latest recorded steps value."""
        record = self._record
        if record is None:
            return None
        value = record.get("steps")
        return int(value) if isinstance(value, int | float) else None

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._record is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the source record attributes."""
        return self._record or {}

    @property
    def _record(self) -> dict[str, Any] | None:
        """Return the latest steps record."""
        if not self.coordinator.data:
            return None
        record = self.coordinator.data.get("latest_steps")
        return record if isinstance(record, dict) else None


class EndurainSleepSensor(EndurainEntity, SensorEntity):
    """Latest sleep duration sensor."""

    _attr_icon = "mdi:sleep"
    _attr_name = "Latest Sleep"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "h"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sleep sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_latest_sleep"

    @property
    def native_value(self) -> float | None:
        """Return the latest total sleep duration in hours."""
        record = self._record
        if record is None:
            return None
        value = record.get("total_sleep_seconds")
        if not isinstance(value, int | float):
            return None
        return round(float(value) / 3600, 2)

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._record is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sleep metadata."""
        return self._record or {}

    @property
    def _record(self) -> dict[str, Any] | None:
        """Return the latest sleep record."""
        if not self.coordinator.data:
            return None
        record = self.coordinator.data.get("latest_sleep")
        return record if isinstance(record, dict) else None


class EndurainWeightSensor(EndurainEntity, SensorEntity):
    """Latest weight sensor."""

    _attr_icon = "mdi:scale-bathroom"
    _attr_name = "Latest Weight"
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the weight sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_latest_weight"

    @property
    def native_value(self) -> float | None:
        """Return the latest weight in kg."""
        record = self._record
        if record is None:
            return None
        value = record.get("weight")
        return round(float(value), 2) if isinstance(value, int | float) else None

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._record is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return weight metadata."""
        return self._record or {}

    @property
    def _record(self) -> dict[str, Any] | None:
        """Return the latest weight record."""
        if not self.coordinator.data:
            return None
        record = self.coordinator.data.get("latest_weight")
        return record if isinstance(record, dict) else None


class EndurainGearCountSensor(EndurainEntity, SensorEntity):
    """Total number of tracked gear items."""

    _attr_icon = "mdi:bike-fast"
    _attr_name = "Gear Count"

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the gear count sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_gear_count"

    @property
    def native_value(self) -> int | None:
        """Return the number of gear items."""
        if not self.coordinator.data:
            return None
        gear_stats = self.coordinator.data.get("gear_stats")
        if not isinstance(gear_stats, list):
            return None
        return len(gear_stats)


class EndurainGoalSensor(EndurainEntity, SensorEntity):
    """Dynamic goal completion sensor."""

    _attr_icon = "mdi:flag-checkered"
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry, goal_id: int) -> None:
        """Initialize the goal sensor."""
        super().__init__(coordinator, entry)
        self._goal_id = goal_id
        self._attr_unique_id = f"{entry.entry_id}_goal_{goal_id}"

    @property
    def name(self) -> str:
        """Return the sensor name."""
        goal = self._goal
        if goal is None:
            return "Goal Progress"
        interval = str(goal.get("interval", "goal")).replace("_", " ").title()
        activity_type = str(goal.get("activity_type", "Activity")).replace("_", " ").title()
        goal_type = str(goal.get("goal_type", "progress")).replace("_", " ").title()
        return f"{interval} {activity_type} {goal_type}"

    @property
    def native_value(self) -> int | None:
        """Return goal completion percentage."""
        goal = self._goal
        if goal is None:
            return None
        value = goal.get("percentage_completed")
        return int(value) if isinstance(value, int | float) else None

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._goal is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return goal progress attributes."""
        goal = self._goal
        if goal is None:
            return {}
        attrs = dict(goal)
        if isinstance(attrs.get("total_distance"), int | float):
            attrs["total_distance_km"] = round(float(attrs["total_distance"]) / 1000, 2)
        if isinstance(attrs.get("goal_distance"), int | float):
            attrs["goal_distance_km"] = round(float(attrs["goal_distance"]) / 1000, 2)
        if isinstance(attrs.get("total_duration"), int | float):
            attrs["total_duration_hours"] = round(float(attrs["total_duration"]) / 3600, 2)
        if isinstance(attrs.get("goal_duration"), int | float):
            attrs["goal_duration_hours"] = round(float(attrs["goal_duration"]) / 3600, 2)
        return attrs

    @property
    def _goal(self) -> dict[str, Any] | None:
        """Return the goal payload for this entity."""
        if not self.coordinator.data:
            return None
        for goal in self.coordinator.data.get("goals", []):
            if isinstance(goal, dict) and goal.get("goal_id") == self._goal_id:
                return goal
        return None


class EndurainGearSensor(EndurainEntity, SensorEntity):
    """Dynamic gear distance sensor."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:shoe-sneaker"

    def __init__(
        self,
        coordinator: EndurainCoordinator,
        entry: ConfigEntry,
        unique_suffix: int | str,
    ) -> None:
        """Initialize the gear sensor."""
        super().__init__(coordinator, entry)
        self._unique_suffix = str(unique_suffix)
        self._attr_unique_id = f"{entry.entry_id}_gear_{unique_suffix}"

    @property
    def name(self) -> str:
        """Return the gear sensor name."""
        gear = self._gear
        if gear is None:
            return "Gear Distance"
        nickname = gear.get("nickname") or "Gear"
        return f"{nickname} Distance"

    @property
    def native_value(self) -> float | None:
        """Return the cumulative distance for this gear."""
        gear = self._gear
        if gear is None:
            return None
        value = gear.get("total_distance_km")
        return round(float(value), 2) if isinstance(value, int | float) else None

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self._gear is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return gear usage metadata."""
        gear = self._gear
        if gear is None:
            return {}
        attrs = dict(gear)
        last_activity = attrs.pop("last_activity", None)
        if isinstance(last_activity, dict):
            attrs["last_activity_name"] = last_activity.get("name")
            attrs["last_activity_at"] = (
                last_activity.get("start_time_tz_applied")
                or last_activity.get("start_time")
                or last_activity.get("created_at_tz_applied")
                or last_activity.get("created_at")
            )
            attrs["last_activity_distance_km"] = round(
                float(last_activity.get("distance", 0.0)) / 1000,
                2,
            )
        return attrs

    @property
    def _gear(self) -> dict[str, Any] | None:
        """Return the gear payload for this entity."""
        if not self.coordinator.data:
            return None
        for gear in self.coordinator.data.get("gear_stats", []):
            if not isinstance(gear, dict):
                continue
            gear_id = gear.get("id")
            fallback = slugify(str(gear.get("nickname", "gear")))
            if str(gear_id) == self._unique_suffix or fallback == self._unique_suffix:
                return gear
        return None
