"""
Sensor platform for Kelvinator Home Comfort integration.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CloudACDevice
from .const import DOMAIN
from .coordinator import KelvinatorCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: list[SensorEntityDescription] = [
    SensorEntityDescription(
        key="ambient_temp",
        name="Ambient Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="error_code",
        name="Error Code",
    ),
    SensorEntityDescription(
        key="timer",
        name="Timer",
    ),
    SensorEntityDescription(
        key="schedule_time",
        name="Schedule Time",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KelvinatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[KelvinatorSensor] = []
    for did, device in coordinator.devices.items():
        for desc in SENSOR_TYPES:
            entities.append(KelvinatorSensor(coordinator, did, device, desc))
    async_add_entities(entities)

    @callback
    def _add_new() -> None:
        current = {(e._did, e._key) for e in entities}
        new = []
        for did, device in coordinator.devices.items():
            for desc in SENSOR_TYPES:
                if (did, desc.key) not in current:
                    e = KelvinatorSensor(coordinator, did, device, desc)
                    entities.append(e)
                    new.append(e)
        if new:
            async_add_entities(new)

    coordinator.async_add_listener(_add_new)


class KelvinatorSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KelvinatorCoordinator,
        did: str,
        device: CloudACDevice,
        description: SensorEntityDescription,
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
    def native_value(self) -> Any:
        s = self._device.state
        if self._key == "ambient_temp":
            return s.ambient_temp if s.ambient_temp > 0 else None
        elif self._key == "error_code":
            return None if s.error_code == 0 else str(s.error_code)
        elif self._key == "timer":
            return None
        elif self._key == "schedule_time":
            return None
        return None

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
