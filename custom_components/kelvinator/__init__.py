"""
Kelvinator Home Comfort integration for Home Assistant.

Control Kelvinator/Electrolux air conditioners via BroadLink DNA protocol.
Uses the bundled kelvinator_dna package for cloud discovery and device control.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import KelvinatorCoordinator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Work around a broadlink library crash that affects our devices.
#
# The installed broadlink library's scan() (device.py:72) does
#   name = resp[0x40:].split(b"\\x00")[0].decode()
# without a fallback encoding.  Kelvinator ACs respond to the Broadlink
# DHCP discovery probe with a byte 0xff at offset 0x40, which is not
# valid UTF-8.  scan() raises UnicodeDecodeError, which propagates up
# through the HA broadlink config_flow and manifests as an unhandled
# "Task exception was never retrieved" / config_flow.py:77 crash.
#
# We monkey-patch scan() so that devices with undecodable names are
# silently skipped rather than crashing the whole discovery.
# ---------------------------------------------------------------------------

def _patch_broadlink_scan() -> None:
    try:
        import broadlink.device as _bl_device  # type: ignore[import-untyped]
    except ImportError:
        return  # broadlink library not installed — nothing to patch

    _original_scan = _bl_device.scan

    def _safe_scan(*args, **kwargs):
        gen = _original_scan(*args, **kwargs)
        while True:
            try:
                yield next(gen)
            except UnicodeDecodeError:
                _LOGGER.debug(
                    "broadlink scan skipped a device with non-UTF-8 "
                    "name (likely a Kelvinator AC)"
                )
                continue
            except StopIteration:
                return

    _bl_device.scan = _safe_scan
    _LOGGER.debug("Patched broadlink.device.scan to tolerate non-UTF-8 names")


_patch_broadlink_scan()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kelvinator from a config entry."""
    username: str = entry.data["username"]
    password: str = entry.data["password"]
    country_code: str = entry.data.get("country_code", "61")
    poll_interval: int = entry.options.get(
        "poll_interval", entry.data.get("poll_interval", 30)
    )

    coordinator = KelvinatorCoordinator(
        hass,
        username=username,
        password=password,
        country_code=country_code,
        poll_interval=poll_interval,
    )

    await coordinator._async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
