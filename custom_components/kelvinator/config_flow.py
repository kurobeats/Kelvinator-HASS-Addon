"""
Config flow for the Kelvinator Home Comfort integration.

Single-step UI: collect BroadLink cloud account credentials.
Devices are auto-discovered from the cloud after login.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import KelvinatorCloudClient
from .const import (
    CONF_COUNTRY_CODE,
    CONF_POLL_INTERVAL,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


STEP_ACCOUNT_SCHEMA = vol.Schema(
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
        """Collect account credentials and validate against cloud."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                cloud = KelvinatorCloudClient(
                    country_code=user_input.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
                )
                await cloud.login(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
                _LOGGER.info("Cloud login validated OK")
            except Exception as exc:
                _LOGGER.warning("Login validation failed: %s", exc)
                errors["base"] = "invalid_auth"
                return self.async_show_form(
                    step_id="user",
                    data_schema=STEP_ACCOUNT_SCHEMA,
                    errors=errors,
                )

            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Kelvinator Home Comfort",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_ACCOUNT_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return KelvinatorOptionsFlow(config_entry)


class KelvinatorOptionsFlow(config_entries.OptionsFlow):
    """Options flow: adjust poll interval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Options: poll interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self._entry.options.get(
            CONF_POLL_INTERVAL,
            self._entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_POLL_INTERVAL, default=current): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
