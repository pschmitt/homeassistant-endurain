"""Repair helpers for Endurain."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def _issue_id(entry: ConfigEntry) -> str:
    """Build the repair issue ID for one config entry."""
    return f"{entry.entry_id}_auth_failed"


def async_create_auth_issue(hass: HomeAssistant, entry: ConfigEntry, details: str) -> None:
    """Create or refresh the auth repair issue."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="auth_failed",
        translation_placeholders={
            "title": entry.title,
            "details": details,
        },
    )


def async_delete_auth_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the auth repair issue."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
