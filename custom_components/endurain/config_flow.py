"""Config flow for Endurain."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import EndurainApiClient
from .const import (
    CONF_API_KEY_EXPIRES_AT,
    CONF_ENABLE_GEARS,
    CONF_ENABLE_GOALS,
    CONF_ENABLE_HEALTH,
    CONF_ENABLE_LIFETIME,
    DEFAULT_ENABLE_GEARS,
    DEFAULT_ENABLE_GOALS,
    DEFAULT_ENABLE_HEALTH,
    DEFAULT_ENABLE_LIFETIME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .exceptions import EndurainApiError, EndurainAuthError, EndurainRateLimitError

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def normalize_url(value: str) -> str:
    """Normalize the configured URL."""
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


async def validate_api_key(
    hass: HomeAssistant, url: str, verify_ssl: bool, api_key: str
) -> dict[str, Any]:
    """Check an API key and return the profile it belongs to."""
    session = async_create_clientsession(hass, verify_ssl=verify_ssl)
    client = EndurainApiClient(session=session, base_url=url, api_key=api_key)
    return await client.async_fetch_profile()


def _error_key(err: Exception) -> str:
    """Map an exception to a config flow error key."""
    if isinstance(err, EndurainRateLimitError):
        return "rate_limited"
    if isinstance(err, EndurainAuthError):
        return "invalid_auth"
    if isinstance(err, EndurainApiError):
        return "cannot_connect"
    _LOGGER.exception("Unexpected error in the Endurain config flow", exc_info=err)
    return "unknown"


class EndurainConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Endurain; the integration authenticates with an API key."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EndurainOptionsFlow:
        """Return the options flow."""
        return EndurainOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Set up Endurain with a server URL and an API key."""
        return await self._async_step_key("user", user_input, {})

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start a reauth flow when the API key no longer works or expires soon."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        return await self._async_step_key(
            "reauth_confirm", user_input, dict(self._get_reauth_entry().data)
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Change the server, or replace the API key."""
        return await self._async_step_key(
            "reconfigure", user_input, dict(self._get_reconfigure_entry().data)
        )

    async def _async_step_key(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> ConfigFlowResult:
        """Shared form: server URL, SSL verification and the API key."""
        errors: dict[str, str] = {}
        url = current.get(CONF_URL, DEFAULT_URL)
        verify_ssl = current.get(CONF_VERIFY_SSL, True)
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            verify_ssl = user_input[CONF_VERIFY_SSL]
            api_key = (user_input.get(CONF_API_KEY) or "").strip() or current.get(CONF_API_KEY, "")
            if not api_key:
                errors[CONF_API_KEY] = "api_key_required"
            else:
                try:
                    profile = await validate_api_key(self.hass, url, verify_ssl, api_key)
                except Exception as err:  # noqa: BLE001
                    errors["base"] = _error_key(err)
                else:
                    return await self._async_finish(profile, url, verify_ssl, api_key, current)

        # Only reconfigure can keep the current key; a reauth means it stopped working.
        key_field = (
            vol.Optional(CONF_API_KEY) if step_id == "reconfigure" else vol.Required(CONF_API_KEY)
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=url): TextSelector(),
                    key_field: PASSWORD_SELECTOR,
                    vol.Required(CONF_VERIFY_SSL, default=verify_ssl): BooleanSelector(),
                }
            ),
            description_placeholders={"name": current.get(CONF_USERNAME) or url},
            errors=errors,
        )

    async def _async_finish(
        self,
        profile: dict[str, Any],
        url: str,
        verify_ssl: bool,
        api_key: str,
        current: dict[str, Any],
    ) -> ConfigFlowResult:
        """Create or update the entry for a validated key."""
        username = str(profile.get("username") or "")
        unique_id = f"{url}|{username}"
        data: dict[str, Any] = {
            CONF_URL: url,
            CONF_VERIFY_SSL: verify_ssl,
            CONF_USERNAME: username,
            CONF_API_KEY: api_key,
        }

        if self.source == "user":
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=profile.get("name") or username or "Endurain",
                data=data,
                options={
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    CONF_ENABLE_GOALS: DEFAULT_ENABLE_GOALS,
                    CONF_ENABLE_HEALTH: DEFAULT_ENABLE_HEALTH,
                    CONF_ENABLE_GEARS: DEFAULT_ENABLE_GEARS,
                    CONF_ENABLE_LIFETIME: DEFAULT_ENABLE_LIFETIME,
                },
            )

        entry = (
            self._get_reauth_entry() if self.source == "reauth" else self._get_reconfigure_entry()
        )
        if entry.unique_id and entry.unique_id != unique_id:
            return self.async_abort(reason="wrong_account")
        if api_key == current.get(CONF_API_KEY) and current.get(CONF_API_KEY_EXPIRES_AT):
            # Same key: its known expiry still applies. A new key's expiry is unknown,
            # since an API key cannot read the key list.
            data[CONF_API_KEY_EXPIRES_AT] = current[CONF_API_KEY_EXPIRES_AT]
        if entry.state is ConfigEntryState.LOADED:
            # The entry's update listener reloads it.
            return self.async_update_and_abort(entry, data=data)
        return self.async_update_reload_and_abort(entry, data=data)


class EndurainOptionsFlow(OptionsFlow):
    """Handle Endurain options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            step=60,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_ENABLE_GOALS,
                        default=options.get(CONF_ENABLE_GOALS, DEFAULT_ENABLE_GOALS),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_HEALTH,
                        default=options.get(CONF_ENABLE_HEALTH, DEFAULT_ENABLE_HEALTH),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_GEARS,
                        default=options.get(CONF_ENABLE_GEARS, DEFAULT_ENABLE_GEARS),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_LIFETIME,
                        default=options.get(CONF_ENABLE_LIFETIME, DEFAULT_ENABLE_LIFETIME),
                    ): BooleanSelector(),
                }
            ),
        )
