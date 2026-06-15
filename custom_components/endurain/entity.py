"""Entity helpers for Endurain."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EndurainCoordinator


class EndurainEntity(CoordinatorEntity[EndurainCoordinator]):
    """Base entity for Endurain."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EndurainCoordinator, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the shared Endurain service device."""
        profile = self.coordinator.data.get("profile", {}) if self.coordinator.data else {}
        about = self.coordinator.data.get("about", {}) if self.coordinator.data else {}
        username = profile.get("username") or self._entry.data.get("username")
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"Endurain ({username})" if username else "Endurain",
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Endurain Project",
            model="Endurain",
            sw_version=about.get("version"),
            configuration_url=self._entry.data.get("url"),
        )
