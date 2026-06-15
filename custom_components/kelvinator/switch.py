"""
Switch platform for Kelvinator Home Comfort integration.

Exposes power, display, sleep, and eco toggles for each AC unit.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CloudACDevice
from .const import DOMAIN
from .coordinator import KelvinatorCoordinator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Switch descriptions
# ---------------------------------------------------------------------------

SWITCH_TYPES: list[SwitchEntityDescription] = [
    SwitchEntityDescription(
        key="power",
        name="Power",
        icon="mdi:power",
    ),
    SwitchEntityDescription(
        key="display",
        name="Display",
        icon="mdi:monitor-shimmer",
    ),
    SwitchEntityDescription(
        key="sleep",
        name="Sleep",
        icon="mdi:sleep",
    ),
    SwitchEntityDescription(
        key="eco",
        name="ECO",
        icon="mdi:leaf",
    ),
]


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kelvinator switch entities from a config entry."""
    coordinator: KelvinatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[KelvinatorSwitch] = []
    for mac, device in coordinator.devices.items():
        for desc in SWITCH_TYPES:
            entities.append(KelvinatorSwitch(coordinator, mac, device, desc))

    async_add_entities(entities)

    # Dynamically add switches for newly discovered devices
    @callback
    def _async_add_new_devices() -> None:
        current_ids = {e.unique_id for e in entities}
        new_entities: list[KelvinatorSwitch] = []
        for mac, device in coordinator.devices.items():
            for desc in SWITCH_TYPES:
                uid = f"kelvinator_ac_{mac.replace(':', '_').lower()}_{desc.key}"
                if uid not in current_ids:
                    entity = KelvinatorSwitch(coordinator, mac, device, desc)
                    entities.append(entity)
                    new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_async_add_new_devices)


class KelvinatorSwitch(SwitchEntity):
    """Switch entity for a single Kelvinator AC unit property."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KelvinatorCoordinator,
        mac: str,
        device: CloudACDevice,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        self._coordinator = coordinator
        self._mac = mac
        self._device = device
        self.entity_description = description
        self._key = description.key

        self._attr_unique_id = (
            f"kelvinator_ac_{mac.replace(':', '_').lower()}_{self._key}"
        )
        self._attr_name = f"{device.name} {description.name}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.mac)},
            "name": device.name,
            "manufacturer": "Kelvinator",
            "model": device.state.model_number or "Unknown",
            "sw_version": "BroadLink DNA",
        }

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def is_on(self) -> bool:
        s = self._device.state
        if self._key == "power":
            return s.power
        elif self._key == "display":
            return s.display_on
        elif self._key == "sleep":
            return s.sleep
        elif self._key == "eco":
            return s.eco
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_switch(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_switch(False)

    async def _set_switch(self, on: bool) -> None:
        dev = self._device
        if self._key == "power":
            await dev.set_power(on)
        elif self._key == "display":
            await dev.set_display(on)
        elif self._key == "sleep":
            await dev.set_sleep(on)
        elif self._key == "eco":
            await dev.set_eco(on)
        await self._coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._mac in self._coordinator.devices:
            self._device = self._coordinator.devices[self._mac]
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
