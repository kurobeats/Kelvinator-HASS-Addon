"""
Kelvinator-DNA: Kelvinator/Electrolux AC control using the BroadLink DNA protocol.

This package provides a complete Python library for controlling
Kelvinator and Electrolux air conditioners that use the BroadLink Wi-Fi module
(devtype=0x4F9B / 20379, pid=9b4f0000).

Architecture:
  - broadlink_api/     — Reverse-engineered libNetworkAPI.so protocol
                          (0x38-byte header, AES-128-CBC, UDP transport)
  - protocol.py         — AC-specific TFB payload builder/parser
  - device.py           — KelvinatorDevice wrapping broadlink_api.BroadlinkDevice
  - commands.py         — ACMode, FanSpeed, SwingMode, ACState
  - cloud.py            — BroadLink cloud API (HTTPS REST)
  - cli.py              — Command-line interface
  - so_bridge.py        — ctypes wrapper for libNetworkAPI.so (cloud relay)

Protocol details:
  - Broadlink DNA header: 56 bytes (0x38) with device type, ID, MAC, timestamp
  - Encryption: AES-128-CBC with PKCS7 padding
  - IV derivation: MD5(device_key + device_id_as_u32_le)
  - Checksum: 2-byte little-endian sum prepended before encryption
  - AC payload: TFB blocks [param_id:1][len:1][val:N] inside decrypted envelope
"""

from .cloud import (
    KelvinatorCloud,
    DeviceInfo,
    CloudCredentials,
    load_cached_devices,
    save_cached_devices,
)
from .device import (
    KelvinatorDevice,
    DeviceStatus,
    discover_devices,
)
from .commands import ACMode, FanSpeed, SwingMode, ACState
from .so_bridge import NetworkAPI

__version__ = "0.2.0"
__all__ = [
    # Cloud
    "KelvinatorCloud",
    "DeviceInfo",
    "CloudCredentials",
    "load_cached_devices",
    "save_cached_devices",
    # Device
    "KelvinatorDevice",
    "DeviceStatus",
    "discover_devices",
    # Commands
    "ACMode",
    "FanSpeed",
    "SwingMode",
    "ACState",
    # SO Bridge
    "NetworkAPI",
]
