"""
Kelvinator Home Comfort integration for Home Assistant.

Control Kelvinator air conditioners via BroadLink DNA protocol (LAN + cloud relay).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import KelvinatorCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kelvinator from a config entry."""
    username: str = entry.data["username"]
    password: str = entry.data["password"]
    country_code: str = entry.data.get("country_code", "61")
    poll_interval: int = entry.data.get("poll_interval", 30)

    coordinator = KelvinatorCoordinator(
        hass,
        username=username,
        password=password,
        country_code=country_code,
        poll_interval=poll_interval,
    )

    # Run initial discovery and first refresh
    await coordinator._async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: KelvinatorCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok
