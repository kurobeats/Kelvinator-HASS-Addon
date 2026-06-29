"""
Commands: AC mode, fan speed, swing mode enums and state container
for Kelvinator/Electrolux air conditioners.
"""

from dataclasses import dataclass
from enum import IntEnum


class ACMode(IntEnum):
    """Air conditioner operation modes."""
    COOL = 0
    HEAT = 1
    AUTO = 2
    FAN = 3
    DRY = 4


class FanSpeed(IntEnum):
    """Fan speed settings (verified against HAR telemetry).

    The Kelvinator app uses the internal name ``ac_mark`` for fan speed.
    Values 0-3 are standard speeds; 5 is the TURBO / maximum-speed mode.
    (Value 4 is skipped in the real app.)
    """
    AUTO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    TURBO = 5


class SwingMode(IntEnum):
    """Swing/louver direction modes.

    HAR telemetry shows ``ac_vdir`` with values 0 (off) and 1 (vertical on).
    Horizontal and both modes are defined in the protocol but not yet observed.
    """
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
    screen_display: bool = True  # Screen display brightness on/off
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
            'screen_display': self.screen_display,
            'temp_unit': self.temp_unit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ACState":
        return cls(
            power=data.get('power', False),
            mode=data.get('mode', ACMode.COOL),
            temp=data.get('temp', 24),
            fan=data.get('fan', FanSpeed.AUTO),
            swing=data.get('swing', SwingMode.OFF),
            sleep=data.get('sleep', False),
            turbo=data.get('turbo', False),
            screen_display=data.get('screen_display', True),
            temp_unit=data.get('temp_unit', 0),
        )

    def __repr__(self) -> str:
        mode_names = {0: "COOL", 1: "HEAT", 2: "AUTO", 3: "FAN", 4: "DRY"}
        fan_names = {0: "AUTO", 1: "LOW", 2: "MED", 3: "HIGH", 5: "TURBO"}
        swing_names = {0: "OFF", 1: "VERT", 2: "HORIZ", 3: "BOTH"}

        parts = [
            f"power={'ON' if self.power else 'OFF'}",
            f"mode={mode_names.get(self.mode, str(self.mode))}",
            f"temp={self.temp}°C",
            f"fan={fan_names.get(self.fan, str(self.fan))}",
            f"swing={swing_names.get(self.swing, str(self.swing))}",
        ]
        if self.sleep:
            parts.append("sleep=ON")
        if self.turbo:
            parts.append("turbo=ON")
        if not self.screen_display:
            parts.append("display=OFF")
        return f"ACState({', '.join(parts)})"
