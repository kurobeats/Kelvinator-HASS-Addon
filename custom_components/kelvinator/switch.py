"""
Switch platform for Kelvinator Home Comfort integration.
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

SWITCH_TYPES: list[SwitchEntityDescription] = [
    SwitchEntityDescription(key="power", name="Power"),
    SwitchEntityDescription(key="display", name="Display"),
    SwitchEntityDescription(key="sleep", name="Sleep"),
    SwitchEntityDescription(key="eco", name="Eco"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KelvinatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[KelvinatorSwitch] = []
    for did, device in coordinator.devices.items():
        for desc in SWITCH_TYPES:
            entities.append(KelvinatorSwitch(coordinator, did, device, desc))
    async_add_entities(entities)

    @callback
    def _add_new() -> None:
        current = {(e._did, e._key) for e in entities}
        new = []
        for did, device in coordinator.devices.items():
            for desc in SWITCH_TYPES:
                if (did, desc.key) not in current:
                    e = KelvinatorSwitch(coordinator, did, device, desc)
                    entities.append(e)
                    new.append(e)
        if new:
            async_add_entities(new)

    coordinator.async_add_listener(_add_new)


class KelvinatorSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KelvinatorCoordinator,
        did: str,
        device: CloudACDevice,
        description: SwitchEntityDescription,
    ) -> None:
        self._coordinator = coordinator
        self._did = did
        self._device = device
        self.entity_description = description
        self._key = description.key
        mac_s = device.mac.replace(":", "_").lower()
        self._attr_unique_id = f"kelvinator_ac_{mac_s}_{self._key}"
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
        await self._toggle(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle(False)

    async def _toggle(self, on: bool) -> None:
        key = self._key
        s = self._device.state
        if key == "power":
            await self._device.send_command({"power": 1 if on else 0})
            s.power = on
        elif key == "display":
            await self._device.send_command({"display": 1 if on else 0})
            s.display_on = on
        elif key == "sleep":
            await self._device.send_command({"sleep": 1 if on else 0})
            s.sleep = on
        elif key == "eco":
            await self._device.send_command({"eco": 1 if on else 0})
            s.eco = on
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._did in self._coordinator.devices:
            self._device = self._coordinator.devices[self._did]
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
