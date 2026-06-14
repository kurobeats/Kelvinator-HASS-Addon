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
    poll_interval: int = entry.options.get("poll_interval", entry.data.get("poll_interval", 30))
    device_hosts: list[str] = entry.options.get("device_hosts", entry.data.get("device_hosts", []))
    enable_discovery: bool = entry.options.get("enable_discovery", entry.data.get("enable_discovery", True))

    coordinator = KelvinatorCoordinator(
        hass,
        username=username,
        password=password,
        country_code=country_code,
        poll_interval=poll_interval,
        device_hosts=device_hosts,
        enable_discovery=enable_discovery,
    )

    # Run initial discovery and first refresh
    await coordinator._async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register listener so options changes (add/remove IPs) take effect
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change (device IPs added/removed)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: KelvinatorCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok
