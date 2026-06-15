"""Service registration for Endurain."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_BULK_IMPORT,
    SERVICE_REFRESH_ACTIVITIES,
    SERVICE_IMPORT_STRAVA_BIKES,
    SERVICE_IMPORT_STRAVA_SHOES,
    SERVICE_SYNC_RECENT_STRAVA,
    SERVICE_SYNC_STRAVA_GEAR,
)


SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
    }
)

SYNC_RECENT_STRAVA_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("days", default=7): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register Endurain services."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH_ACTIVITIES):
        return

    async def async_refresh_activities(call: ServiceCall) -> None:
        entry, client, coordinator = _resolve_entry(hass, call.data)
        del entry
        await client.async_refresh_activities()
        await coordinator.async_request_refresh()

    async def async_sync_recent_strava(call: ServiceCall) -> None:
        entry, client, coordinator = _resolve_entry(hass, call.data)
        del entry
        await client.async_sync_recent_strava(int(call.data["days"]))
        await coordinator.async_request_refresh()

    async def async_sync_strava_gear(call: ServiceCall) -> None:
        entry, client, coordinator = _resolve_entry(hass, call.data)
        del entry
        await client.async_sync_strava_gear()
        await coordinator.async_request_refresh()

    async def async_bulk_import(call: ServiceCall) -> None:
        entry, client, coordinator = _resolve_entry(hass, call.data)
        del entry
        await client.async_bulk_import()
        await coordinator.async_request_refresh()

    async def async_import_strava_shoes(call: ServiceCall) -> None:
        entry, client, coordinator = _resolve_entry(hass, call.data)
        del entry
        await client.async_import_strava_shoes()
        await coordinator.async_request_refresh()

    async def async_import_strava_bikes(call: ServiceCall) -> None:
        entry, client, coordinator = _resolve_entry(hass, call.data)
        del entry
        await client.async_import_strava_bikes()
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_ACTIVITIES,
        async_refresh_activities,
        schema=SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_RECENT_STRAVA,
        async_sync_recent_strava,
        schema=SYNC_RECENT_STRAVA_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_STRAVA_GEAR,
        async_sync_strava_gear,
        schema=SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BULK_IMPORT,
        async_bulk_import,
        schema=SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STRAVA_SHOES,
        async_import_strava_shoes,
        schema=SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STRAVA_BIKES,
        async_import_strava_bikes,
        schema=SERVICE_SCHEMA,
    )


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Endurain services."""
    for service in (
        SERVICE_REFRESH_ACTIVITIES,
        SERVICE_SYNC_RECENT_STRAVA,
        SERVICE_SYNC_STRAVA_GEAR,
        SERVICE_BULK_IMPORT,
        SERVICE_IMPORT_STRAVA_SHOES,
        SERVICE_IMPORT_STRAVA_BIKES,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


def _resolve_entry(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> tuple[ConfigEntry, Any, Any]:
    """Resolve the target config entry for a service call."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("No Endurain config entry is loaded")

    entry_id = data.get("config_entry_id")
    if entry_id:
        entry = next((item for item in entries if item.entry_id == entry_id), None)
        if entry is None:
            raise HomeAssistantError(f"Unknown Endurain config entry: {entry_id}")
    elif len(entries) == 1:
        entry = entries[0]
    else:
        raise HomeAssistantError(
            "Multiple Endurain config entries are loaded; specify config_entry_id"
        )

    runtime = hass.data[DOMAIN][entry.entry_id]
    return entry, runtime["client"], runtime["coordinator"]
