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
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
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

from .api import EndurainAccountSession, EndurainApiClient
from .const import (
    CONF_API_KEY_EXPIRES_AT,
    CONF_API_KEY_ID,
    CONF_DEVICE_ID,
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
from .exceptions import (
    EndurainApiError,
    EndurainAuthError,
    EndurainMfaRequiredError,
    EndurainRateLimitError,
)
from .provision import async_create_key_data

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
    if isinstance(err, EndurainMfaRequiredError):
        return "mfa_required"
    if isinstance(err, EndurainRateLimitError):
        return "rate_limited"
    if isinstance(err, EndurainAuthError):
        return "invalid_auth"
    if isinstance(err, EndurainApiError):
        return "cannot_connect"
    _LOGGER.exception("Unexpected error in the Endurain config flow", exc_info=err)
    return "unknown"


class EndurainConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Endurain.

    The integration authenticates with an Endurain API key. A user either pastes a
    key or signs in once with username and password, and the flow creates the key;
    the password is never stored.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._url: str = DEFAULT_URL
        self._verify_ssl: bool = True
        self._username: str | None = None
        self._password: str | None = None
        self._account: EndurainAccountSession | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EndurainOptionsFlow:
        """Return the options flow."""
        return EndurainOptionsFlow(config_entry)

    # Setup

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask for the server and an optional API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._url = normalize_url(user_input[CONF_URL])
            self._verify_ssl = user_input[CONF_VERIFY_SSL]
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            if not api_key:
                return await self.async_step_credentials()
            try:
                profile = await validate_api_key(self.hass, self._url, self._verify_ssl, api_key)
            except Exception as err:  # noqa: BLE001
                errors["base"] = _error_key(err)
            else:
                return await self._async_finish(profile, {CONF_API_KEY: api_key})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=self._url): TextSelector(),
                    vol.Optional(CONF_API_KEY): PASSWORD_SELECTOR,
                    vol.Required(CONF_VERIFY_SSL, default=self._verify_ssl): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_credentials(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Sign in once to create an API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._account = EndurainAccountSession(
                session=async_create_clientsession(self.hass, verify_ssl=self._verify_ssl),
                base_url=self._url,
                device_id=self._existing_entry_data().get(CONF_DEVICE_ID),
            )
            try:
                await self._account.async_login(self._username, self._password)
            except EndurainMfaRequiredError:
                return await self.async_step_mfa()
            except Exception as err:  # noqa: BLE001
                errors["base"] = _error_key(err)
            else:
                return await self._async_create_key(None)

        return self._show_credentials_form(errors.get("base"))

    async def async_step_mfa(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Answer the MFA step of the sign-in."""
        errors: dict[str, str] = {}
        if user_input is not None and self._account is not None:
            try:
                await self._account.async_verify_mfa(user_input[CONF_MFA_CODE])
            except Exception as err:  # noqa: BLE001
                errors["base"] = (
                    "invalid_mfa" if isinstance(err, EndurainAuthError) else _error_key(err)
                )
            else:
                # Creating the key needs the second factor again, and Endurain accepts
                # each code only once.
                return await self.async_step_step_up()

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({vol.Required(CONF_MFA_CODE): TextSelector()}),
            errors=errors,
        )

    async def async_step_step_up(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask for the next MFA code to confirm the API key creation."""
        if user_input is not None:
            return await self._async_create_key(user_input[CONF_MFA_CODE])
        return self.async_show_form(
            step_id="step_up",
            data_schema=vol.Schema({vol.Required(CONF_MFA_CODE): TextSelector()}),
        )

    async def _async_create_key(self, mfa_code: str | None) -> ConfigFlowResult:
        """Create the API key on the signed-in session and finish the flow."""
        if self._account is None or self._password is None:
            return self.async_abort(reason="unknown")
        try:
            profile = await self._account.async_fetch_profile()
            # Check the account before creating a key, so an aborted flow leaves no
            # key behind.
            unique_id = f"{self._url}|{profile.get('username')}"
            if self.source == "user":
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
            else:
                entry = (
                    self._get_reauth_entry()
                    if self.source == "reauth"
                    else self._get_reconfigure_entry()
                )
                if entry.unique_id and entry.unique_id != unique_id:
                    return self.async_abort(reason="wrong_account")
            key_data = await async_create_key_data(
                self._account,
                password=self._password,
                mfa_code=mfa_code,
                previous_key_id=self._existing_entry_data().get(CONF_API_KEY_ID),
            )
        except AbortFlow:
            raise
        except (EndurainMfaRequiredError, EndurainAuthError) as err:
            if mfa_code is None and not isinstance(err, EndurainMfaRequiredError):
                self._password = None
                return self._show_credentials_form("invalid_auth")
            # The account wants a (new) second factor for the step-up: keep the
            # signed-in session and the password, and ask for the next code.
            return self.async_show_form(
                step_id="step_up",
                data_schema=vol.Schema({vol.Required(CONF_MFA_CODE): TextSelector()}),
                errors={"base": "invalid_mfa" if mfa_code else "mfa_required"},
            )
        except Exception as err:  # noqa: BLE001
            self._password = None
            return self._show_credentials_form(_error_key(err))
        self._password = None
        return await self._async_finish(profile, key_data)

    def _show_credentials_form(self, error: str | None = None) -> ConfigFlowResult:
        """Show the sign-in form, optionally with an error."""
        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self._username
                        or self._existing_entry_data().get(CONF_USERNAME, ""),
                    ): TextSelector(),
                    vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            errors={"base": error} if error else {},
        )

    async def _async_finish(
        self, profile: dict[str, Any], key_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create or update the entry for a validated key."""
        username = str(profile.get("username") or self._username or "")
        data: dict[str, Any] = {
            CONF_URL: self._url,
            CONF_VERIFY_SSL: self._verify_ssl,
            CONF_USERNAME: username,
            **key_data,
        }
        unique_id = f"{self._url}|{username}"

        if self.source in ("reauth", "reconfigure"):
            entry = (
                self._get_reauth_entry()
                if self.source == "reauth"
                else self._get_reconfigure_entry()
            )
            if entry.unique_id and entry.unique_id != unique_id:
                return self.async_abort(reason="wrong_account")
            if CONF_API_KEY in key_data and CONF_API_KEY_ID not in key_data:
                # A pasted key: forget the metadata of the key it replaces.
                data[CONF_API_KEY_ID] = None
                data[CONF_API_KEY_EXPIRES_AT] = None
            new_data = {
                key: value
                for key, value in {**entry.data, **data}.items()
                if key not in (CONF_PASSWORD, CONF_MFA_CODE) and value is not None
            }
            if entry.state is ConfigEntryState.LOADED:
                # The entry's update listener reloads it.
                return self.async_update_and_abort(entry, data=new_data)
            return self.async_update_reload_and_abort(entry, data=new_data)

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=profile.get("name") or username or "Endurain",
            data={key: value for key, value in data.items() if value is not None},
            options={
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_ENABLE_GOALS: DEFAULT_ENABLE_GOALS,
                CONF_ENABLE_HEALTH: DEFAULT_ENABLE_HEALTH,
                CONF_ENABLE_GEARS: DEFAULT_ENABLE_GEARS,
                CONF_ENABLE_LIFETIME: DEFAULT_ENABLE_LIFETIME,
            },
        )

    def _existing_entry_data(self) -> dict[str, Any]:
        """Return the data of the entry being reauthenticated or reconfigured."""
        if self.source == "reauth":
            return dict(self._get_reauth_entry().data)
        if self.source == "reconfigure":
            return dict(self._get_reconfigure_entry().data)
        return {}

    # Reauthentication and reconfiguration

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start a reauth flow when the API key no longer works or is about to expire."""
        self._url = entry_data[CONF_URL]
        self._verify_ssl = entry_data.get(CONF_VERIFY_SSL, True)
        self._username = entry_data.get(CONF_USERNAME)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask for a new API key, or sign in to create one."""
        return await self._async_step_key("reauth_confirm", user_input)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Change the server, or replace the API key."""
        entry = self._get_reconfigure_entry()
        if user_input is None:
            self._url = entry.data[CONF_URL]
            self._verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
            self._username = entry.data.get(CONF_USERNAME)
        return await self._async_step_key("reconfigure", user_input)

    async def _async_step_key(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Shared form of reauth and reconfigure: URL, SSL and an optional new key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._url = normalize_url(user_input[CONF_URL])
            self._verify_ssl = user_input[CONF_VERIFY_SSL]
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            if not api_key and step_id == "reconfigure":
                api_key = self._existing_entry_data().get(CONF_API_KEY, "")
            if not api_key:
                return await self.async_step_credentials()
            try:
                profile = await validate_api_key(self.hass, self._url, self._verify_ssl, api_key)
            except Exception as err:  # noqa: BLE001
                errors["base"] = _error_key(err)
            else:
                key_data: dict[str, Any] = {CONF_API_KEY: api_key}
                if api_key == self._existing_entry_data().get(CONF_API_KEY):
                    key_data = {}
                return await self._async_finish(profile, key_data)

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=self._url): TextSelector(),
                    vol.Optional(CONF_API_KEY): PASSWORD_SELECTOR,
                    vol.Required(CONF_VERIFY_SSL, default=self._verify_ssl): BooleanSelector(),
                }
            ),
            description_placeholders={"name": self._username or self._url},
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
