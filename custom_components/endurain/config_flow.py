"""Config flow for Endurain."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import BooleanSelector, NumberSelector, NumberSelectorConfig, NumberSelectorMode, TextSelector, TextSelectorConfig, TextSelectorType

from .api import EndurainApiClient
from .const import (
    CONF_ENABLE_GEARS,
    CONF_ENABLE_GOALS,
    CONF_ENABLE_HEALTH,
    CONF_ENABLE_LIFETIME,
    CONF_MFA_CODE,
    DEFAULT_ENABLE_GEARS,
    DEFAULT_ENABLE_GOALS,
    DEFAULT_ENABLE_HEALTH,
    DEFAULT_ENABLE_LIFETIME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .exceptions import EndurainApiError, EndurainAuthError, EndurainMfaRequiredError, EndurainRateLimitError

_LOGGER = logging.getLogger(__name__)


def normalize_url(value: str) -> str:
    """Normalize the configured URL."""
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate config flow input."""
    session = async_create_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL])
    client = EndurainApiClient(
        session=session,
        base_url=data[CONF_URL],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        mfa_code=data.get(CONF_MFA_CODE),
    )
    result = await client.async_validate(mfa_code=data.get(CONF_MFA_CODE))
    profile = result["profile"]
    title = profile.get("name") or profile.get("username") or "Endurain"
    unique_id = f"{data[CONF_URL]}|{profile.get('username', data[CONF_USERNAME])}"
    return {"title": title, "unique_id": unique_id}


class EndurainConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Endurain."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "EndurainOptionsFlow":
        """Return the options flow."""
        return EndurainOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial setup flow."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_URL] = normalize_url(user_input[CONF_URL])
            try:
                info = await validate_input(self.hass, user_input)
            except EndurainMfaRequiredError:
                errors["base"] = "mfa_required"
            except EndurainRateLimitError:
                errors["base"] = "rate_limited"
            except EndurainAuthError:
                errors["base"] = "invalid_auth"
            except EndurainApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception while validating Endurain config")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                data = {
                    CONF_URL: user_input[CONF_URL],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                }
                if user_input.get(CONF_MFA_CODE):
                    data[CONF_MFA_CODE] = user_input[CONF_MFA_CODE]
                return self.async_create_entry(
                    title=info["title"],
                    data=data,
                    options={
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_ENABLE_GOALS: DEFAULT_ENABLE_GOALS,
                        CONF_ENABLE_HEALTH: DEFAULT_ENABLE_HEALTH,
                        CONF_ENABLE_GEARS: DEFAULT_ENABLE_GEARS,
                        CONF_ENABLE_LIFETIME: DEFAULT_ENABLE_LIFETIME,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): TextSelector(),
                    vol.Required(CONF_USERNAME): TextSelector(),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_MFA_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_VERIFY_SSL, default=True): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            user_input[CONF_URL] = normalize_url(user_input[CONF_URL])
            password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            data = {
                CONF_URL: user_input[CONF_URL],
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: password,
                CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
            }
            if user_input.get(CONF_MFA_CODE):
                data[CONF_MFA_CODE] = user_input[CONF_MFA_CODE]
            elif entry.data.get(CONF_MFA_CODE):
                data[CONF_MFA_CODE] = entry.data[CONF_MFA_CODE]

            try:
                info = await validate_input(self.hass, data)
            except EndurainMfaRequiredError:
                errors["base"] = "mfa_required"
            except EndurainRateLimitError:
                errors["base"] = "rate_limited"
            except EndurainAuthError:
                errors["base"] = "invalid_auth"
            except EndurainApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception while reconfiguring Endurain")
                errors["base"] = "unknown"
            else:
                new_unique_id = info["unique_id"]
                for other in self._async_current_entries():
                    if other.entry_id != entry.entry_id and other.unique_id == new_unique_id:
                        return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    data=data,
                    unique_id=new_unique_id,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=entry.data[CONF_URL]): TextSelector(),
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): TextSelector(),
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_MFA_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        CONF_VERIFY_SSL,
                        default=entry.data.get(CONF_VERIFY_SSL, True),
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a reauth flow."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle user confirmation during reauth."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            data = dict(entry.data)
            data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            if user_input.get(CONF_MFA_CODE):
                data[CONF_MFA_CODE] = user_input[CONF_MFA_CODE]
            else:
                data.pop(CONF_MFA_CODE, None)

            try:
                await validate_input(self.hass, data)
            except EndurainMfaRequiredError:
                errors["base"] = "mfa_required"
            except EndurainRateLimitError:
                errors["base"] = "rate_limited"
            except EndurainAuthError:
                errors["base"] = "invalid_auth"
            except EndurainApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception while reauthenticating Endurain")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_MFA_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )


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
