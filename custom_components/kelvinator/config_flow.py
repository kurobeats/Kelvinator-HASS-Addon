"""
Config flow for the Kelvinator Home Comfort integration.

Two-step UI flow:
  1. Account credentials + LAN discovery toggle
  2. Device IP addresses (comma-separated)

Also provides an Options flow for adding/removing IPs post-setup.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import probe_device
from .const import (
    CONF_COUNTRY_CODE,
    CONF_DEVICE_HOSTS,
    CONF_ENABLE_DISCOVERY,
    CONF_POLL_INTERVAL,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _validate_ips(raw: str) -> list[str]:
    """Parse comma-separated IP/host list, strip whitespace, filter empties."""
    if not raw.strip():
        return []
    return [h.strip() for h in raw.split(",") if h.strip()]


# ---------------------------------------------------------------------------
# Step 1: Account credentials
# ---------------------------------------------------------------------------

STEP_ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_COUNTRY_CODE, default=DEFAULT_COUNTRY_CODE): str,
        vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): int,
        vol.Optional(CONF_ENABLE_DISCOVERY, default=True): bool,
    }
)


class KelvinatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kelvinator Home Comfort."""

    VERSION = 1

    def __init__(self) -> None:
        self._account_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: collect account credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._account_data = user_input
            return await self.async_step_devices()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_ACCOUNT_SCHEMA,
            errors=errors,
        )

    # -------------------------------------------------- Step 2: Device IPs

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: enter device IP addresses."""
        errors: dict[str, str] = {}
        current_hosts = user_input.get(CONF_DEVICE_HOSTS, "") if user_input else ""

        if user_input is not None:
            ips = _validate_ips(user_input[CONF_DEVICE_HOSTS])

            # Probe each IP to validate at least one responds
            probed = 0
            for ip in ips:
                dev = await probe_device(ip, timeout=5)
                if dev is not None:
                    probed += 1

            if not ips and not self._account_data.get(CONF_ENABLE_DISCOVERY, True):
                errors[CONF_DEVICE_HOSTS] = "enter_at_least_one_ip"

            if ips and probed == 0:
                errors[CONF_DEVICE_HOSTS] = "no_device_responded"

            if not errors:
                # Merge account + device data
                full_data = {**self._account_data, CONF_DEVICE_HOSTS: ips}
                await self.async_set_unique_id(
                    f"kelvinator_{self._account_data[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Kelvinator Home Comfort",
                    data=full_data,
                )

        # Build schema with current value
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEVICE_HOSTS,
                    default=current_hosts,
                    description={"suggested_value": current_hosts},
                ): str,
            }
        )

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
            description_placeholders={
                "example": "192.168.1.50, 192.168.1.51, 192.168.1.52"
            },
            errors=errors,
        )

    # -------------------------------------------------- Options flow

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return KelvinatorOptionsFlow(config_entry)


class KelvinatorOptionsFlow(config_entries.OptionsFlow):
    """Options flow: add/remove device IPs and adjust settings post-setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage device IPs and poll interval."""
        if user_input is not None:
            ips = _validate_ips(user_input[CONF_DEVICE_HOSTS])
            return self.async_create_entry(
                data={
                    **self._entry.data,
                    CONF_DEVICE_HOSTS: ips,
                    CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                    CONF_ENABLE_DISCOVERY: user_input.get(CONF_ENABLE_DISCOVERY, True),
                }
            )

        current_hosts = self._entry.data.get(CONF_DEVICE_HOSTS, [])
        hosts_str = ", ".join(current_hosts) if isinstance(current_hosts, list) else str(current_hosts)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEVICE_HOSTS,
                    default=hosts_str,
                    description={"suggested_value": hosts_str},
                ): str,
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=self._entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): int,
                vol.Optional(
                    CONF_ENABLE_DISCOVERY,
                    default=self._entry.data.get(CONF_ENABLE_DISCOVERY, True),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "example": "192.168.1.50, 192.168.1.51"
            },
        )