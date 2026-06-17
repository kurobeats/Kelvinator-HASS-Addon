"""
Commands: AC mode, fan speed, swing mode enums and state container.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class ACMode(IntEnum):
    """Air conditioner operation modes."""
    COOL = 0
    HEAT = 1
    AUTO = 2
    FAN = 3
    DRY = 4


class FanSpeed(IntEnum):
    """Fan speed settings."""
    AUTO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class SwingMode(IntEnum):
    """Swing/louver direction modes."""
    OFF = 0
    VERTICAL = 1
    HORIZONTAL = 2
    BOTH = 3


@dataclass
class ACState:
    """
    Complete AC state for get/set operations.

    Usage:
        state = ACState(power=True, mode=ACMode.COOL, temp=22, fan=FanSpeed.AUTO)
        device.set_state(state)
        # Or read current state:
        status = device.get_status()
        print(f"Current temp: {status.temp}°C")
    """
    power: bool = False
    mode: int = ACMode.COOL
    temp: int = 24
    fan: int = FanSpeed.AUTO
    swing: int = SwingMode.OFF
    sleep: bool = False
    turbo: bool = False
    temp_unit: int = 0  # 0=Celsius, 1=Fahrenheit

    def to_dict(self) -> dict:
        return {
            'power': self.power,
            'mode': int(self.mode),
            'temp': self.temp,
            'fan': int(self.fan),
            'swing': int(self.swing),
            'sleep': self.sleep,
            'turbo': self.turbo,
            'temp_unit': self.temp_unit,
        }
