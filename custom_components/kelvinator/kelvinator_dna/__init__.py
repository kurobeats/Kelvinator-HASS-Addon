"""
Kelvinator-DNA: Reverse-engineered Python library for the
Electrolux/Kelvinator air conditioner control using the BroadLink DNA protocol.

This library allows control of Kelvinator AC units that use the BroadLink
Wi-Fi module (devtype=20379, pid=9b4f0000).

Protocol layers:
  - Cloud API: HTTPS REST for device discovery and credential retrieval
  - DNA Protocol: UDP-based encrypted device control protocol
  - TFB Envelope: Type-Field-Body serialization format
  - AES-128-ECB: Encryption of TFB payloads
"""

from .cloud import KelvinatorCloud
from .device import KelvinatorDevice, discover_devices
from .commands import ACMode, FanSpeed, SwingMode, ACState

__version__ = "0.1.0"
__all__ = [
    "KelvinatorCloud",
    "KelvinatorDevice",
    "discover_devices",
    "ACMode",
    "FanSpeed",
    "SwingMode",
    "ACState",
]
