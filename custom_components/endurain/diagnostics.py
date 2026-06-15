"""Diagnostics support for Endurain."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_MFA_CODE, DOMAIN

TO_REDACT = {CONF_PASSWORD, CONF_MFA_CODE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    data = coordinator.data or {}

    return {
        "entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "options": dict(config_entry.options),
        "summary_keys": sorted(data.get("summaries", {}).keys()),
        "goal_count": len(data.get("goals", [])),
        "gear_count": len(data.get("gear_stats", [])),
        "has_steps": data.get("latest_steps") is not None,
        "has_sleep": data.get("latest_sleep") is not None,
        "has_weight": data.get("latest_weight") is not None,
        "profile": data.get("profile", {}),
        "about": data.get("about", {}),
    }
