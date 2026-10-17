"""The Endurain integration."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import EndurainApiClient
from .const import CONF_MFA_CODE, DOMAIN, PLATFORMS
from .coordinator import EndurainCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = f"/{DOMAIN}/activity-heatmap-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "activity-heatmap-card.js"
LEGACY_CARD_URL = f"/local/{CARD_PATH.name}"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Endurain integration, serve card and register resource."""
    del config
    hass.data.setdefault(DOMAIN, {})

    if CARD_PATH.exists():
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
        )
        digest = await hass.async_add_executor_job(
            lambda: hashlib.sha256(CARD_PATH.read_bytes()).hexdigest()[:10]
        )
        await _async_register_card(hass, f"{CARD_URL}?v={digest}")

    return True


async def _async_register_card(hass: HomeAssistant, url: str) -> None:
    """Keep exactly one Lovelace resource pointing at the current card."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != "storage":
        add_extra_js_url(hass, url)
        return
    resources = lovelace.resources
    await resources.async_get_info()

    # Remove legacy /local/ resource if present
    legacy = [
        item for item in resources.async_items() if item["url"].split("?")[0] == LEGACY_CARD_URL
    ]
    for old in legacy:
        await resources.async_delete_item(old["id"])

    mine = [item for item in resources.async_items() if item["url"].split("?")[0] == CARD_URL]
    for duplicate in mine[1:]:
        await resources.async_delete_item(duplicate["id"])
    if not mine:
        _LOGGER.info("Adding Activity Heatmap card as a dashboard resource")
        await resources.async_create_item({"res_type": "module", "url": url})
    elif mine[0]["url"] != url:
        await resources.async_update_item(mine[0]["id"], {"res_type": "module", "url": url})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Endurain from a config entry."""
    session = async_create_clientsession(
        hass,
        verify_ssl=entry.data[CONF_VERIFY_SSL],
    )
    client = EndurainApiClient(
        session=session,
        base_url=entry.data[CONF_URL],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        mfa_code=entry.data.get(CONF_MFA_CODE),
    )
    coordinator = EndurainCoordinator(hass, entry, client)

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    await async_register_services(hass)
    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        "endurain_initial_refresh",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Endurain config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            await async_unregister_services(hass)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration after options changes."""
    await hass.config_entries.async_reload(entry.entry_id)
