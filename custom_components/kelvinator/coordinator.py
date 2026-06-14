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
    probe_device,
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
        device_host: str = "",
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
        self._device_host = device_host
        self._cloud: BroadLinkCloudClient | None = None
        self.devices: dict[str, KelvinatorACDevice] = {}

    async def _async_setup(self) -> None:
        """Discover devices. Called once on entry setup."""
        # 1. Cloud login — get device list from BroadLink cloud
        self._cloud = BroadLinkCloudClient(country_code=self._country_code)
        cloud_devices: list[dict] = []
        try:
            await self._cloud.login(self._username, self._password)
            _LOGGER.info("BroadLink cloud login OK")
            cloud_devices = await self._cloud.list_devices()
            _LOGGER.info("Cloud returned %d device(s)", len(cloud_devices))
        except Exception as exc:
            _LOGGER.warning("Cloud login failed (LAN-only mode): %s", exc)

        # 2. Discover devices on LAN
        if self._device_host:
            # Direct probe mode — user specified an IP
            _LOGGER.info("Probing device at %s...", self._device_host)
            dev = await probe_device(self._device_host, timeout=10)
            if dev is not None:
                self.devices[dev.mac] = dev
        else:
            # UDP broadcast discovery
            _LOGGER.info("Discovering BroadLink devices on LAN...")
            discovered = await discover_devices(timeout=5)
            for dev in discovered:
                self.devices[dev.mac] = dev

        # 3. Merge cloud device info (names, etc.) into LAN-discovered devices
        for cd in cloud_devices:
            mac = cd.get("mac", "")
            if mac and mac in self.devices:
                # Enrich existing LAN device with cloud name
                self.devices[mac]._name = cd.get("name", self.devices[mac]._name)

        # 4. Connect and get initial state
        if not self.devices:
            _LOGGER.warning("No Kelvinator AC devices discovered")
        else:
            for dev in self.devices.values():
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
