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
        self._device_hosts = device_hosts or []
        self._enable_discovery = enable_discovery
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

        # 2. Direct probe — user specified IPs
        if self._device_hosts:
            _LOGGER.info("Probing %d device(s)...", len(self._device_hosts))
            for host in self._device_hosts:
                dev = await probe_device(host, timeout=10)
                if dev is not None:
                    self.devices[dev.mac] = dev

        # 2. UDP broadcast discovery (if enabled)
        if not self._device_hosts or self._enable_discovery:
            _LOGGER.info("Discovering BroadLink devices on LAN...")
            discovered = await discover_devices(timeout=5)
            for dev in discovered:
                if dev.mac not in self.devices:
                    self.devices[dev.mac] = dev

        if not self.devices:
            _LOGGER.warning("No Kelvinator AC devices discovered")
        else:
            # Enrich LAN devices with cloud names
            for cd in cloud_devices:
                mac = cd.get("mac", "")
                if mac and mac in self.devices:
                    self.devices[mac]._name = cd.get("name", self.devices[mac]._name)

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
        # 1. Poll existing devices
        for dev in list(self.devices.values()):
            ok = await dev.update_state()
            if not ok:
                _LOGGER.warning("Device %s unreachable", dev.name)

        # 2. Probe any user-specified IPs not yet discovered
        for host in self._device_hosts:
            if not any(d.host == host for d in self.devices.values()):
                dev = await probe_device(host, timeout=5)
                if dev is not None and dev.mac not in self.devices:
                    self.devices[dev.mac] = dev
                    if await dev.connect():
                        await dev.update_state()
                        _LOGGER.info("New device from configured IP: %s", dev.name)

        # 3. Also try re-discovering via UDP if no devices found
        if not self.devices and self._enable_discovery:
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
