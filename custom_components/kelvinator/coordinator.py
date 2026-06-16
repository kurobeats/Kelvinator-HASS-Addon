"""
DataUpdateCoordinator for the Kelvinator Home Comfort integration.

Cloud-first: discovers devices via BroadLink cloud API,
controls them via DNA protocol (cloud relay or local UDP).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KelvinatorCloudClient, KelvinatorACDevice, get_dna_relay
from .const import DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class KelvinatorCoordinator(DataUpdateCoordinator[dict[str, KelvinatorACDevice]]):
    """Coordinates discovery and polling of all Kelvinator AC devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        country_code: str = "61",
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self._username = username
        self._password = password
        self._country_code = country_code
        self._cloud: KelvinatorCloudClient | None = None
        self._relay = None
        self.devices: dict[str, KelvinatorACDevice] = {}

    async def _async_setup(self) -> None:
        """Discover devices from cloud. Called once on entry setup."""
        self._cloud = KelvinatorCloudClient(country_code=self._country_code)

        try:
            await self._cloud.login(self._username, self._password)
        except Exception as exc:
            raise UpdateFailed(f"Cloud login failed: {exc}") from exc

        self._relay = get_dna_relay()
        if self._relay:
            _LOGGER.info("DNA cloud relay initialized")
        else:
            _LOGGER.info("DNA relay not available — state polling disabled")

        cloud_devices = await self._cloud.discover_devices()
        _LOGGER.info("Cloud returned %d device(s)", len(cloud_devices))

        for cd in cloud_devices:
            if not cd.did:
                continue
            self.devices[cd.did] = KelvinatorACDevice(info=cd, relay=self._relay)

        if not self.devices:
            raise UpdateFailed("No Kelvinator AC devices found in cloud account")

        _LOGGER.info("Registered %d devices: %s", len(self.devices), ", ".join(d.name for d in self.devices.values()))

    async def _async_update_data(self) -> dict[str, KelvinatorACDevice]:
        """Poll device state via cloud relay or local DNA."""
        try:
            cloud_devices = await self._cloud.discover_devices()
            for cd in cloud_devices:
                if cd.did and cd.did not in self.devices:
                    self.devices[cd.did] = KelvinatorACDevice(info=cd, relay=self._relay)
                    _LOGGER.info("New device: %s", cd.name)
        except Exception as exc:
            _LOGGER.error("Failed to refresh cloud device list: %s", exc)

        for dev in self.devices.values():
            await dev.update_state()

        return self.devices
