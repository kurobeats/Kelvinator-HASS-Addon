"""
Sensor platform for Kelvinator Home Comfort integration.

Exposes read-only sensors: ambient temperature, error code, timer, schedule.
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

from .api import KelvinatorACDevice
from .const import DOMAIN
from .coordinator import KelvinatorCoordinator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensor descriptions
# ---------------------------------------------------------------------------

SENSOR_TYPES: list[SensorEntityDescription] = [
    SensorEntityDescription(
        key="ambient_temp",
        name="Ambient Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
    ),
    SensorEntityDescription(
        key="error_code",
        name="Error Code",
        icon="mdi:alert-circle",
    ),
    SensorEntityDescription(
        key="timer",
        name="Timer",
        icon="mdi:timer-outline",
    ),
    SensorEntityDescription(
        key="schedule_enabled",
        name="Schedule",
        icon="mdi:calendar-clock",
    ),
    SensorEntityDescription(
        key="schedule_time",
        name="Schedule Time",
        icon="mdi:clock-outline",
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
    """Set up Kelvinator sensor entities from a config entry."""
    coordinator: KelvinatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[KelvinatorSensor] = []
    for mac, device in coordinator.devices.items():
        for desc in SENSOR_TYPES:
            entities.append(KelvinatorSensor(coordinator, mac, device, desc))

    async_add_entities(entities)

    # Dynamically add sensors for newly discovered devices
    @callback
    def _async_add_new_devices() -> None:
        current_ids = {e.unique_id for e in entities}
        new_entities: list[KelvinatorSensor] = []
        for mac, device in coordinator.devices.items():
            for desc in SENSOR_TYPES:
                uid = f"kelvinator_ac_{mac.replace(':', '_').lower()}_{desc.key}"
                if uid not in current_ids:
                    entity = KelvinatorSensor(coordinator, mac, device, desc)
                    entities.append(entity)
                    new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_async_add_new_devices)


class KelvinatorSensor(SensorEntity):
    """Sensor entity for a single Kelvinator AC unit."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KelvinatorCoordinator,
        mac: str,
        device: KelvinatorACDevice,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
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
    def native_value(self) -> Any:
        s = self._device.state
        if self._key == "ambient_temp":
            return s.ambient_temp if s.ambient_temp > 0 else None
        elif self._key == "error_code":
            return None if s.error_code == "0" else s.error_code
        elif self._key == "timer":
            return s.timer or None
        elif self._key == "schedule_enabled":
            return "On" if s.schedule_enabled else "Off"
        elif self._key == "schedule_time":
            return s.schedule_time or None
        return None

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
