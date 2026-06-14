"""
Climate platform for Kelvinator Home Comfort integration.

Exposes each Kelvinator AC unit as a Home Assistant ClimateEntity.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import KelvinatorACDevice
from .const import (
    DOMAIN,
    FAN_KELVINATOR_TO_HA,
    FAN_MODES,
    HVAC_MODES,
    MODE_KELVINATOR_TO_HA,
    SWING_MODES,
)
from .coordinator import KelvinatorCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kelvinator climate entities from a config entry."""
    coordinator: KelvinatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create one entity per discovered device
    entities: list[KelvinatorClimate] = []
    for mac, device in coordinator.devices.items():
        entities.append(KelvinatorClimate(coordinator, mac, device))

    async_add_entities(entities)

    # Register a listener to add newly discovered devices dynamically
    @callback
    def _async_add_new_devices() -> None:
        current_macs = {e.mac for e in entities}
        new_entities: list[KelvinatorClimate] = []
        for mac, device in coordinator.devices.items():
            if mac not in current_macs:
                entity = KelvinatorClimate(coordinator, mac, device)
                entities.append(entity)
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_async_add_new_devices)


class KelvinatorClimate(ClimateEntity):
    """Climate entity for a single Kelvinator AC unit."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = HVAC_MODES
    _attr_fan_modes = FAN_MODES
    _attr_swing_modes = SWING_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: KelvinatorCoordinator,
        mac: str,
        device: KelvinatorACDevice,
    ) -> None:
        """Initialize the climate entity."""
        self._coordinator = coordinator
        self._mac = mac
        self._device = device

        self._attr_unique_id = f"kelvinator_ac_{mac.replace(':', '_').lower()}"
        self._attr_name = device.name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.mac)},
            "name": device.name,
            "manufacturer": "Kelvinator",
            "model": device.state.model_number or "Unknown",
            "sw_version": "BroadLink DNA",
        }

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def current_temperature(self) -> float | None:
        return self._device.state.ambient_temp

    @property
    def target_temperature(self) -> float | None:
        return float(self._device.state.target_temp)

    @property
    def min_temp(self) -> float:
        return float(self._device.state.temp_min_c)

    @property
    def max_temp(self) -> float:
        return float(self._device.state.temp_max_c)

    @property
    def hvac_mode(self) -> HVACMode | None:
        if not self._device.state.power:
            return HVACMode.OFF
        return HVACMode(MODE_KELVINATOR_TO_HA.get(
            self._device.state.mode, "auto"
        ))

    @property
    def fan_mode(self) -> str | None:
        return FAN_KELVINATOR_TO_HA.get(
            self._device.state.fan_speed, "auto"
        )

    @property
    def swing_mode(self) -> str | None:
        s = self._device.state
        if s.swing_vertical and s.swing_horizontal:
            return "both"
        elif s.swing_vertical:
            return "vertical"
        elif s.swing_horizontal:
            return "horizontal"
        return "off"

    # -------------------------------------------------- Commands

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self._device.set_temperature(int(temp))
            await self._coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._device.set_hvac_mode(hvac_mode.value)
        await self._coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._device.set_fan_mode(fan_mode)
        await self._coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._device.set_swing_mode(swing_mode)
        await self._coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self._device.set_power(True)
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._device.set_power(False)
        await self._coordinator.async_request_refresh()

    # -------------------------------------------------- Coordinator

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        # Device may have been replaced in coordinator.devices dict
        if self._mac in self._coordinator.devices:
            self._device = self._coordinator.devices[self._mac]
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
