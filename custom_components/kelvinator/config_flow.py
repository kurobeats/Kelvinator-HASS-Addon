"""
Config flow for the Kelvinator Home Comfort integration.

Provides a UI form for users to enter their Kelvinator account credentials.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .api import BroadLinkCloudClient
from .const import (
    CONF_COUNTRY_CODE,
    CONF_POLL_INTERVAL,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config flow schema
# ---------------------------------------------------------------------------

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_COUNTRY_CODE, default=DEFAULT_COUNTRY_CODE): str,
        vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): int,
    }
)


class KelvinatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kelvinator Home Comfort."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: collect credentials and validate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate credentials against BroadLink cloud
            try:
                cloud = BroadLinkCloudClient()
                await cloud.login(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                await cloud.close()
            except RuntimeError as exc:
                _LOGGER.warning("Login validation failed: %s", exc)
                errors["base"] = "invalid_auth"
            except Exception as exc:
                _LOGGER.error("Unexpected error during validation: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                # Ensure single instance per account
                await self.async_set_unique_id(
                    f"kelvinator_{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Kelvinator Home Comfort",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )