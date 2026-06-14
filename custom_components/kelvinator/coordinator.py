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
        self.devices: dict[str, KelvinatorACDevice] = {}

    async def _async_setup(self) -> None:
        """Discover devices on LAN. Called once on entry setup."""
        # The integration works via LAN discovery (BroadLink DNA protocol).
        # Cloud relay is not yet supported.
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
        """Shutdown coordinator."""
        # No persistent connections to close in LAN-only mode.
