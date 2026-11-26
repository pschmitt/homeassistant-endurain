"""Create the API key the integration authenticates with."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import CONF_API_KEY

from .api import EndurainAccountSession
from .const import API_KEY_NAME, CONF_API_KEY_EXPIRES_AT, CONF_API_KEY_ID, CONF_DEVICE_ID
from .exceptions import EndurainApiError

_LOGGER = logging.getLogger(__name__)


async def async_create_key_data(
    account: EndurainAccountSession,
    *,
    password: str,
    mfa_code: str | None = None,
    previous_key_id: str | None = None,
) -> dict[str, Any]:
    """Create an API key on a signed-in session and return the entry data for it.

    The key that ``previous_key_id`` names, one the integration created earlier, is
    revoked once the new one exists, so renewals do not pile up keys on the account.
    """
    key = await account.async_create_api_key(
        name=API_KEY_NAME, password=password, mfa_code=mfa_code
    )
    if previous_key_id and previous_key_id != key.get("id"):
        try:
            await account.async_revoke_api_key(previous_key_id)
        except EndurainApiError as err:
            # The new key works either way; the old one expires on its own.
            _LOGGER.warning("Could not revoke the previous Endurain API key: %s", err)
    data: dict[str, Any] = {
        CONF_API_KEY: key["key"],
        CONF_API_KEY_ID: key.get("id"),
        CONF_API_KEY_EXPIRES_AT: key.get("expires_at"),
    }
    if account.device_id:
        data[CONF_DEVICE_ID] = account.device_id
    return data
