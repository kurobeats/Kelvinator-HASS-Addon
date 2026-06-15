"""
DataUpdateCoordinator for the Kelvinator Home Comfort integration.

Cloud-only — all communication goes via BroadLink cloud API.
No LAN discovery or direct device communication required.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BroadLinkCloudClient, CloudACDevice
from .const import DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class KelvinatorCoordinator(DataUpdateCoordinator[dict[str, CloudACDevice]]):
    """Coordinates polling of all Kelvinator AC devices via cloud API."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        country_code: str = "61",
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        device_hosts: list[str] | None = None,
        enable_discovery: bool = True,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self._username = username
        self._password = password
        self._country_code = country_code
        self._cloud: BroadLinkCloudClient | None = None
        self.devices: dict[str, CloudACDevice] = {}

    async def _async_setup(self) -> None:
        """Discover devices from cloud. Called once on entry setup."""
        self._cloud = BroadLinkCloudClient(country_code=self._country_code)

        try:
            await self._cloud.login(self._username, self._password)
            _LOGGER.info("BroadLink cloud login OK")
        except Exception as exc:
            _LOGGER.error("Cloud login failed: %s", exc)
            raise UpdateFailed(f"Cloud login failed: {exc}") from exc

        # Discover devices from cloud (not LAN)
        cloud_devices = await self._cloud.list_devices()
        _LOGGER.info("Cloud returned %d device(s)", len(cloud_devices))

        for cd in cloud_devices:
            did = cd.get("did", "")
            if not did:
                continue
            self.devices[did] = CloudACDevice(
                cloud=self._cloud,
                did=did,
                mac=cd.get("mac", ""),
                name=cd.get("name", "Kelvinator AC"),
                pid=cd.get("pid", ""),
            )

        if not self.devices:
            _LOGGER.error("No Kelvinator AC devices found in cloud account")
            raise UpdateFailed("No devices found in cloud account")

        _LOGGER.info(
            "Registered %d cloud devices: %s",
            len(self.devices),
            ", ".join(d.name for d in self.devices.values()),
        )

    async def _async_update_data(self) -> dict[str, CloudACDevice]:
        """Poll device state via cloud API (no LAN required)."""
        # Re-list devices from cloud in case new ones appeared
        try:
            cloud_devices = await self._cloud.list_devices()
        except Exception as exc:
            _LOGGER.error("Failed to list cloud devices: %s", exc)
            raise UpdateFailed(f"Cloud device list failed: {exc}") from exc

        # Merge cloud devices into our registry
        for cd in cloud_devices:
            did = cd.get("did", "")
            if not did:
                continue
            if did not in self.devices:
                self.devices[did] = CloudACDevice(
                    cloud=self._cloud,
                    did=did,
                    mac=cd.get("mac", ""),
                    name=cd.get("name", "Kelvinator AC"),
                    pid=cd.get("pid", ""),
                )
                _LOGGER.info("New cloud device: %s", cd.get("name"))

        # TODO: Poll actual state from cloud private data API
        # For now, devices report as available with default state

        return self.devices

    async def async_shutdown(self) -> None:
        """Shutdown coordinator, close cloud session."""
        if self._cloud:
            await self._cloud.close()
