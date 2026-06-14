"""
DataUpdateCoordinator for the Kelvinator Home Comfort integration.

Polls all discovered Kelvinator AC devices at a configurable interval.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BroadLinkCloudClient,
    KelvinatorACDevice,
    discover_devices,
)
from .const import DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class KelvinatorCoordinator(DataUpdateCoordinator[dict[str, KelvinatorACDevice]]):
    """Coordinates polling of all Kelvinator AC devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        country_code: str = "61",
        poll_interval: int = DEFAULT_POLL_INTERVAL,
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
        self.devices: dict[str, KelvinatorACDevice] = {}

    async def _async_setup(self) -> None:
        """Login to cloud and discover devices. Called once on entry setup."""
        # 1. Cloud login (non-fatal — devices may be LAN-only)
        self._cloud = BroadLinkCloudClient()
        try:
            await self._cloud.login(self._username, self._password)
            _LOGGER.info("BroadLink cloud login OK")
        except Exception as exc:
            _LOGGER.warning("Cloud login failed (LAN-only mode): %s", exc)

        # 2. Discover devices on LAN
        _LOGGER.info("Discovering BroadLink devices on LAN...")
        discovered = await discover_devices(timeout=5)

        if not discovered:
            _LOGGER.warning("No Kelvinator AC devices discovered on LAN")
        else:
            for dev in discovered:
                self.devices[dev.mac] = dev
                if await dev.connect():
                    await dev.update_state()
                    _LOGGER.info(
                        "Device %s [%s]: power=%s temp=%d°C",
                        dev.name, dev.mac,
                        dev.state.power, dev.state.target_temp,
                    )

    async def _async_update_data(self) -> dict[str, KelvinatorACDevice]:
        """Poll all devices. Called automatically at each interval."""
        for dev in list(self.devices.values()):
            ok = await dev.update_state()
            if not ok:
                _LOGGER.warning("Device %s unreachable", dev.name)

        # Also try re-discovering in case new devices appeared
        if not self.devices:
            discovered = await discover_devices(timeout=3)
            for dev in discovered:
                if dev.mac not in self.devices:
                    self.devices[dev.mac] = dev
                    if await dev.connect():
                        await dev.update_state()
                        _LOGGER.info("New device: %s", dev.name)

        return self.devices

    async def async_shutdown(self) -> None:
        """Shutdown coordinator, close cloud session."""
        if self._cloud:
            await self._cloud.close()
