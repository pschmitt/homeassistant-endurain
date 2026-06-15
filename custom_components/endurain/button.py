"""Button platform for Endurain."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EndurainEntity


@dataclass(frozen=True)
class EndurainButtonDescription:
    """Description of an Endurain button."""

    key: str
    name: str
    icon: str


BUTTONS: tuple[EndurainButtonDescription, ...] = (
    EndurainButtonDescription("refresh_data", "Refresh Data", "mdi:refresh"),
    EndurainButtonDescription("refresh_activities", "Refresh Activities", "mdi:run-fast"),
    EndurainButtonDescription("sync_strava_gear", "Sync Strava Gear", "mdi:bike-sync"),
    EndurainButtonDescription("bulk_import", "Run Bulk Import", "mdi:database-import"),
    EndurainButtonDescription("import_strava_shoes", "Import Strava Shoes", "mdi:shoe-sneaker"),
    EndurainButtonDescription("import_strava_bikes", "Import Strava Bikes", "mdi:bike"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Endurain buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(EndurainButton(coordinator, entry, description) for description in BUTTONS)


class EndurainButton(EndurainEntity, ButtonEntity):
    """Button entity for Endurain actions."""

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        description: EndurainButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        self._attr_icon = description.icon

    async def async_press(self) -> None:
        """Handle the button press."""
        client = self.coordinator.client
        if self.entity_description.key == "refresh_data":
            await self.coordinator.async_request_refresh()
            return
        if self.entity_description.key == "refresh_activities":
            await client.async_refresh_activities()
        elif self.entity_description.key == "sync_strava_gear":
            await client.async_sync_strava_gear()
        elif self.entity_description.key == "bulk_import":
            await client.async_bulk_import()
        elif self.entity_description.key == "import_strava_shoes":
            await client.async_import_strava_shoes()
        elif self.entity_description.key == "import_strava_bikes":
            await client.async_import_strava_bikes()
        await self.coordinator.async_request_refresh()
