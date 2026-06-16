"""
Climate platform for Kelvinator Home Comfort integration.
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

from .api import CloudACDevice
from .const import (
    DOMAIN,
    FAN_HA_TO_KELVINATOR,
    FAN_KELVINATOR_TO_HA,
    FAN_MODES,
    HVAC_MODES,
    MODE_HA_TO_KELVINATOR,
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
    coordinator: KelvinatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[KelvinatorClimate] = [
        KelvinatorClimate(coordinator, did, dev)
        for did, dev in coordinator.devices.items()
    ]
    async_add_entities(entities)

    @callback
    def _add_new() -> None:
        current = {e._did for e in entities}
        new = [
            KelvinatorClimate(coordinator, did, dev)
            for did, dev in coordinator.devices.items()
            if did not in current
        ]
        if new:
            entities.extend(new)
            async_add_entities(new)

    coordinator.async_add_listener(_add_new)


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
        self, coordinator: KelvinatorCoordinator, did: str, device: CloudACDevice,
    ) -> None:
        self._coordinator = coordinator
        self._did = did
        self._device = device
        mac_s = device.mac.replace(":", "_").lower()
        self._attr_unique_id = f"kelvinator_ac_{mac_s}"
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
    def current_temperature(self) -> float | None:
        t = self._device.state.ambient_temp
        return float(t) if t > 0 else None

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
        return HVACMode(MODE_KELVINATOR_TO_HA.get(self._device.state.mode, "auto"))

    @property
    def fan_mode(self) -> str | None:
        return FAN_KELVINATOR_TO_HA.get(self._device.state.fan, "auto")

    @property
    def swing_mode(self) -> str | None:
        s = self._device.state.swing
        if s == 3:
            return "both"
        elif s == 1:
            return "vertical"
        elif s == 2:
            return "horizontal"
        return "off"

    async def async_set_temperature(self, **kwargs: Any) -> None:
        t = kwargs.get(ATTR_TEMPERATURE)
        if t is not None:
            await self._device.send_command({"temp": int(t)})
            self._device.state.target_temp = int(t)
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._device.send_command({"power": 0})
            self._device.state.power = False
        else:
            mode = MODE_HA_TO_KELVINATOR.get(hvac_mode.value, 4)
            await self._device.send_command({"power": 1, "mode": mode})
            self._device.state.power = True
            self._device.state.mode = int(mode)
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        fan = FAN_HA_TO_KELVINATOR.get(fan_mode, 0)
        await self._device.send_command({"fan": int(fan)})
        self._device.state.fan = int(fan)
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        v = 1 if swing_mode in ("vertical", "both") else 0
        h = 1 if swing_mode in ("horizontal", "both") else 0
        await self._device.send_command({"vdir": v, "hdir": h})
        self._device.state.swing = (1 if v else 0) | (2 if h else 0)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self._device.send_command({"power": 1})
        self._device.state.power = True
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._device.send_command({"power": 0})
        self._device.state.power = False
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
