"""
DataUpdateCoordinator for the Kelvinator Home Comfort integration.

Cloud (HTTPS) for login + device discovery with AES keys. Control/status
goes through the bundled DNA SDK native bridge (dna_native.py).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KelvinatorCloudClient, KelvinatorACDevice
from .const import DEFAULT_LICENSE_ID, DEFAULT_POLL_INTERVAL, DOMAIN
from .dna_native import NativeDNAClient, NativeDNAError

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
        self._native = NativeDNAClient()
        self.devices: dict[str, KelvinatorACDevice] = {}

    async def _async_setup(self) -> None:
        """Discover devices from cloud. Called once on entry setup."""
        self._cloud = KelvinatorCloudClient(country_code=self._country_code)

        try:
            await self._cloud.login(self._username, self._password)
        except Exception as exc:
            raise UpdateFailed(f"Cloud login failed: {exc}") from exc

        cloud_devices = await self._cloud.discover_devices()
        _LOGGER.info("Cloud returned %d device(s)", len(cloud_devices))

        if not self.devices:
            for cd in cloud_devices:
                if not cd.did:
                    continue
                self.devices[cd.did] = KelvinatorACDevice(info=cd, client=self._native)

        if not self.devices:
            raise UpdateFailed("No Kelvinator AC devices found in cloud account")

        # Start the DNA SDK bridge and try SDKAuth (registers the cloud
        # session with the DNA cloud so devices accept our control key).
        try:
            await self._native.start()
            cfg = {
                "license": DEFAULT_LICENSE_ID,
                "packageName": "com.kelvinator.airconditioner",
                "loglevel": 4,
            }
            init = await self._native.sdk_init(cfg)
            _LOGGER.info("DNA SDK init: %s", init.get("msg"))
            auth_params = await self._cloud.sdk_auth_params()
            if auth_params:
                args = [
                    DEFAULT_LICENSE_ID,
                    "98273b1f0638bc7819793d58da055d36",  # COMPANY_ID
                    "com.kelvinator.airconditioner",
                    "203",
                    "HomeAssistant",
                    ",".join(d.mac for d in self.devices.values()),
                    ",".join(d.did for d in self.devices.values()),
                    "9b4f0000",
                    self._cloud.userid or "",
                    self._username,
                    auth_params[0],  # api key
                    auth_params[1],  # server timestamp
                    "2.0.49",
                ]
                auth = await self._native.sdk_auth(args)
                _LOGGER.info("DNA SDKAuth: %s", auth)
            else:
                _LOGGER.warning(
                    "SDKAuth skipped (no API key) — device control may be "
                    "rejected with 'control key expired'"
                )
        except NativeDNAError as exc:
            _LOGGER.warning(
                "DNA SDK bridge unavailable (%s) — device control disabled. "
                "This bundle is x86-64 only.", exc)

        _LOGGER.info(
            "Registered %d devices: %s",
            len(self.devices),
            ", ".join(d.name for d in self.devices.values()),
        )

    async def _async_update_data(self) -> dict[str, KelvinatorACDevice]:
        """Poll device state via the DNA SDK bridge."""
        for dev in self.devices.values():
            await dev.update_state()
        return self.devices

    async def async_shutdown(self) -> None:
        await self._native.stop()
        await super().async_shutdown()