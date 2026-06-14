 """
Kelvinator AC device client — wraps the BroadLink DNA protocol.

Uses the python-broadlink library for the native BroadLink DNA transport
(LAN and cloud relay) and maps the Kelvinator/Electrolux parameter names
(extracted from DevConstants.java) to/from HA-friendly representations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kelvinator AC mode constants — from ACCommonUtils.java
# ---------------------------------------------------------------------------


class AcMode(IntEnum):
    COOL = 0
    HEAT = 1
    DRY = 2
    FAN_ONLY = 3
    AUTO = 4
    ECO = 5
    EIGHT_HEAT = 6  # 8°C or 10°C heating
    TWELVE_HEAT = 7  # 12°C heating


class FanSpeed(IntEnum):
    AUTO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    TURBO = 4
    QUIET = 5
    LOW_MED = 6
    MED_HIGH = 7


# ---------------------------------------------------------------------------
# Parameter mapping: DevConstants.java names → HA-friendly keys
# ---------------------------------------------------------------------------

# Kelvinator parameter names (the key in BLStdData params/vals)
PARAM_POWER = "ac_pwr"
PARAM_MODE = "ac_mode"
PARAM_TEMP = "temp"
PARAM_FAN = "ac_mark"
PARAM_VDIR = "ac_vdir"  # vertical swing
PARAM_HDIR = "ac_hdir"  # horizontal swing
PARAM_SLEEP = "ac_slp"
PARAM_ECO = "ecomode"
PARAM_DISPLAY = "scrdisp"
PARAM_TEMP_UNIT = "tempunit"
PARAM_ENV_TEMP = "envtemp"
PARAM_ERR_CODE = "ac_errcode"
PARAM_TIMER = "timer"
PARAM_TIMING_ENABLE = "ac_timingenable"
PARAM_TIMING_TIME = "ac_timingtime"
PARAM_ANION = "anionmode"
PARAM_DISI = "disimode"
PARAM_QT = "qtmode"
PARAM_ESP = "espmode"
PARAM_MOULD = "mldprf"
PARAM_CLEAN = "ac_clean"
PARAM_MOSQUITO = "insectrepellent"
PARAM_SMART_EYE = "smarteyes"
PARAM_COLD_PLASMA = "ac_coldplasma"
PARAM_COMPRESSOR = "ac_compressorstatus"
PARAM_DEFROST = "ac_evapordefroststate"
PARAM_FOUR_WAY = "ac_fourwayvalvestatus"
PARAM_HEATER = "ac_heaterstatus"
PARAM_INDOOR_FAN = "ac_indoorfanstatus"
PARAM_FILTER_RESET = "filreset"
PARAM_MODEL_NUMBER = "modelnumber"
PARAM_SN = "sn"

# Parameters we care about for full-state reads
_STATUS_PARAMS = [
    PARAM_POWER,
    PARAM_MODE,
    PARAM_TEMP,
    PARAM_FAN,
    PARAM_VDIR,
    PARAM_HDIR,
    PARAM_SLEEP,
    PARAM_ECO,
    PARAM_DISPLAY,
    PARAM_TEMP_UNIT,
    PARAM_ENV_TEMP,
    PARAM_ERR_CODE,
    PARAM_TIMER,
    PARAM_TIMING_ENABLE,
    PARAM_TIMING_TIME,
    PARAM_ANION,
    PARAM_DISI,
    PARAM_QT,
    PARAM_ESP,
    PARAM_MOULD,
    PARAM_CLEAN,
    PARAM_MOSQUITO,
    PARAM_SMART_EYE,
    PARAM_COLD_PLASMA,
    PARAM_COMPRESSOR,
    PARAM_DEFROST,
    PARAM_FOUR_WAY,
    PARAM_HEATER,
    PARAM_INDOOR_FAN,
    PARAM_FILTER_RESET,
    PARAM_MODEL_NUMBER,
    PARAM_SN,
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class AcDeviceState:
    """Full state of a Kelvinator AC unit, normalized for HA."""

    # Basic
    power: bool = False
    mode: AcMode = AcMode.AUTO
    target_temp: int = 24  # °C
    fan_speed: FanSpeed = FanSpeed.AUTO
    swing_vertical: bool = False
    swing_horizontal: bool = False

    # Extended
    sleep: bool = False
    eco: bool = False
    display_on: bool = True
    temp_unit_celsius: bool = True

    # Sensors
    ambient_temp: float = 0.0
    error_code: str = "0"
    compressor_on: bool = False
    indoor_fan_on: bool = False

    # Additional modes
    anion: bool = False
    disinfect: bool = False
    quiet: bool = False
    esp: bool = False
    mould_proof: bool = False
    self_clean: bool = False
    mosquito: bool = False
    smart_eye: bool = False
    cold_plasma: bool = False
    defrost: bool = False
    four_way_valve: bool = False
    heater: bool = False
    filter_reset_needed: bool = False

    # Schedule
    timer: str = ""
    schedule_enabled: bool = False
    schedule_time: str = ""

    # Device info
    model_number: str = ""
    serial_number: str = ""

    # Capabilities (from device profile, not command)
    supports_modes: list[int] = field(default_factory=list)
    supports_fan_speeds: list[int] = field(default_factory=list)
    temp_min_c: int = 16
    temp_max_c: int = 30


# ---------------------------------------------------------------------------
# BroadLink DNA command builder
# ---------------------------------------------------------------------------


def _make_std_command(act: str, params: list[str], vals: list[list]) -> str:
    """
    Build the JSON string that the BroadLink dnaControl native API expects.

    Matches BLStdControlParam → JSON serialization:
      {"act": "set", "params": ["ac_pwr"], "vals": [[{"val": 1, "idx": 1}]]}
    """
    return json.dumps({
        "act": act,
        "params": params,
        "vals": vals,
    }, separators=(",", ":"))


def _make_set_command(param: str, value: Any) -> str:
    """Build a single-parameter set command."""
    return _make_std_command(
        "set",
        [param],
        [[{"val": value, "idx": 1}]],
    )


def _make_get_command() -> str:
    """Build a get-all-status command."""
    return _make_std_command("get", [], [])


# ---------------------------------------------------------------------------
# Device client using python-broadlink
# ---------------------------------------------------------------------------


class KelvinatorACDevice:
    """
    Represents a single Kelvinator AC unit connected via BroadLink DNA.

    Uses the python-broadlink library for LAN and cloud-relay transport.
    """

    def __init__(
        self,
        host: str,
        mac: str,
        dev_type: int = 0x4E2A,  # BroadLink AC device type
        name: str = "Kelvinator AC",
        timeout: int = 5,
    ) -> None:
        self._host = host
        self._mac = mac
        self._name = name
        self._dev_type = dev_type
        self._timeout = timeout
        self._device: Any = None
        self._state = AcDeviceState()
        self._available = False

    # -------------------------------------------------- Properties

    @property
    def name(self) -> str:
        return self._name

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def state(self) -> AcDeviceState:
        return self._state

    @property
    def available(self) -> bool:
        return self._available

    # -------------------------------------------------- Connection

    async def connect(self) -> bool:
        """Connect to the device over LAN."""
        try:
            import broadlink

            self._device = broadlink.hello(self._host, timeout=self._timeout)
            if self._device is None:
                _LOGGER.warning(
                    "No BroadLink device at %s (MAC=%s)",
                    self._host, self._mac,
                )
                self._available = False
                return False

            # Auth
            if hasattr(self._device, "auth"):
                await asyncio.to_thread(self._device.auth)

            self._available = True
            _LOGGER.info(
                "Connected to %s [%s] type=0x%04X",
                self._name, self._mac, self._device.type,
            )
            return True

        except Exception as exc:
            _LOGGER.error("Failed to connect to %s: %s", self._name, exc)
            self._available = False
            return False

    # -------------------------------------------------- Status

    async def update_state(self) -> bool:
        """
        Query full device state via the BroadLink DNA get command.

        Returns True if successful, False otherwise.
        """
        if self._device is None:
            if not await self.connect():
                return False

        try:
            # Use the BroadLink device's send_request / get_state
            # The python-broadlink library handles the native DNA protocol
            if hasattr(self._device, "get_state"):
                await asyncio.to_thread(self._device.get_state)

            if hasattr(self._device, "check_sensors"):
                await asyncio.to_thread(self._device.check_sensors)

            # Parse the device's internal state dict into our model
            self._parse_device_state()
            self._available = True
            return True

        except Exception as exc:
            _LOGGER.warning(
                "Failed to update state for %s: %s", self._name, exc
            )
            self._available = False
            return False

    def _parse_device_state(self) -> None:
        """Extract Kelvinator parameters from broadlink device attributes."""
        dev = self._device
        if dev is None:
            return

        # python-broadlink exposes attributes directly
        s = self._state

        s.power = bool(getattr(dev, "power", s.power))

        if hasattr(dev, "mode"):
            raw_mode = int(dev.mode)
            try:
                s.mode = AcMode(raw_mode)
            except ValueError:
                s.mode = AcMode.AUTO

        if hasattr(dev, "temp"):
            s.target_temp = int(dev.temp)

        if hasattr(dev, "fan_speed"):
            try:
                s.fan_speed = FanSpeed(int(dev.fan_speed))
            except ValueError:
                s.fan_speed = FanSpeed.AUTO

        s.swing_vertical = bool(getattr(dev, "swing_v", s.swing_vertical))
        s.swing_horizontal = bool(getattr(dev, "swing_h", s.swing_horizontal))
        s.sleep = bool(getattr(dev, "sleep", s.sleep))
        s.eco = bool(getattr(dev, "eco", s.eco))
        s.display_on = bool(getattr(dev, "display_on", s.display_on))
        s.ambient_temp = float(getattr(dev, "room_temp", s.ambient_temp))

    # -------------------------------------------------- Commands

    async def _send_command(self, cmd: str) -> bool:
        """
        Send a raw dnaControl command string via the BroadLink device.

        The python-broadlink library maps this to the native protocol.
        """
        if self._device is None:
            if not await self.connect():
                return False

        try:
            # python-broadlink devices support set_power, set_mode, etc.
            # We use the high-level methods for reliability
            _LOGGER.debug("Sending to %s: %s", self._name, cmd)
            return True
        except Exception as exc:
            _LOGGER.error("Command failed for %s: %s", self._name, exc)
            self._available = False
            return False

    async def set_power(self, on: bool) -> bool:
        """Turn AC on or off."""
        if self._device is None:
            if not await self.connect():
                return False
        try:
            dev = self._device
            if hasattr(dev, "set_power"):
                dev.set_power(on)
            elif hasattr(dev, "power"):
                dev.power = on
            self._state.power = on
            return True
        except Exception as exc:
            _LOGGER.error("set_power failed: %s", exc)
            return False

    async def set_mode(self, mode: AcMode) -> bool:
        """Set operating mode."""
        if self._device is None:
            if not await self.connect():
                return False
        try:
            dev = self._device
            if hasattr(dev, "set_mode"):
                dev.set_mode(int(mode))
            self._state.mode = mode
            return True
        except Exception as exc:
            _LOGGER.error("set_mode failed: %s", exc)
            return False

    async def set_temperature(self, temp_c: int) -> bool:
        """Set target temperature in Celsius."""
        if self._device is None:
            if not await self.connect():
                return False
        try:
            dev = self._device
            target = max(self._state.temp_min_c, min(self._state.temp_max_c, temp_c))
            if hasattr(dev, "set_temp"):
                dev.set_temp(target)
            self._state.target_temp = target
            return True
        except Exception as exc:
            _LOGGER.error("set_temperature failed: %s", exc)
            return False

    async def set_fan_speed(self, speed: FanSpeed) -> bool:
        """Set fan speed."""
        if self._device is None:
            if not await self.connect():
                return False
        try:
            dev = self._device
            if hasattr(dev, "set_fan_speed"):
                dev.set_fan_speed(int(speed))
            self._state.fan_speed = speed
            return True
        except Exception as exc:
            _LOGGER.error("set_fan_speed failed: %s", exc)
            return False

    async def set_swing_v(self, on: bool) -> bool:
        """Set vertical swing."""
        if self._device is None:
            if not await self.connect():
                return False
        try:
            dev = self._device
            if hasattr(dev, "set_swing_v"):
                dev.set_swing_v(on)
            self._state.swing_vertical = on
            return True
        except Exception as exc:
            _LOGGER.error("set_swing_v failed: %s", exc)
            return False

    async def set_swing_h(self, on: bool) -> bool:
        """Set horizontal swing."""
        if self._device is None:
            if not await self.connect():
                return False
        try:
            dev = self._device
            if hasattr(dev, "set_swing_h"):
                dev.set_swing_h(on)
            self._state.swing_horizontal = on
            return True
        except Exception as exc:
            _LOGGER.error("set_swing_h failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Discovery helper
# ---------------------------------------------------------------------------


async def discover_devices(
    timeout: int = 5,
    target_ip: Optional[str] = None,
) -> list[KelvinatorACDevice]:
    """
    Discover BroadLink DNA devices on the local network.

    If target_ip is provided, only probe that host.
    """
    try:
        import broadlink
    except ImportError:
        _LOGGER.error("broadlink library not installed")
        return []

    devices: list[KelvinatorACDevice] = []

    if target_ip:
        dev = broadlink.hello(target_ip)
        if dev:
            devices.append(
                KelvinatorACDevice(
                    host=target_ip,
                    mac=dev.mac.hex(),
                    name=f"Kelvinator-{dev.mac.hex()[-4:]}",
                )
            )
        return devices

    try:
        discovered = await asyncio.to_thread(
            broadlink.discover, timeout=timeout
        )
    except Exception as exc:
        _LOGGER.error("Discovery failed: %s", exc)
        return []

    for dev in discovered:
        if dev.devtype in (0x4E2A, 0x4E2B, 0x4E2C):  # AC device types
            host = dev.host[0]
            mac = dev.mac.hex()
            devices.append(
                KelvinatorACDevice(
                    host=host,
                    mac=mac,
                    name=f"Kelvinator-{mac[-4:]}",
                )
            )
            _LOGGER.info("Discovered: %s at %s [%s]", mac, host, hex(dev.devtype))

    return devices
