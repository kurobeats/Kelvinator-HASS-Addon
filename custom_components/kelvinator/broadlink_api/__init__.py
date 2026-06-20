"""
Broadlink DNA Protocol (reverse-engineered from libNetworkAPI.so).

This is a subset of the full broadlink_api library, providing:
  - device.py  — BroadlinkDevice (UDP transport, auth, command send)
  - crypto.py  — AES-128-CBC encryption with checksum
  - protocol.py — 0x38-byte header construction, discovery
"""

from .device import BroadlinkDevice
from .crypto import AESCipher, broadlink_encrypt, broadlink_decrypt, derive_device_key
from .protocol import (
    build_device_command,
    parse_device_response,
    build_discovery_packet,
    parse_discovery_response,
)

__all__ = [
    "BroadlinkDevice",
    "AESCipher",
    "broadlink_encrypt",
    "broadlink_decrypt",
    "derive_device_key",
    "build_device_command",
    "parse_device_response",
    "build_discovery_packet",
    "parse_discovery_response",
]
