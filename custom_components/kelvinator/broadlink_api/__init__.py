"""
Broadlink DNA Protocol (reverse-engineered from libNetworkAPI.so).

Provides the corrected BroadLink DNA protocol implementation matching
python-broadlink library format:
  - device.py     — BroadlinkDevice (UDP transport, auth, command send)
  - crypto.py     — AES-128-CBC with zero-padding (no checksum prepended)
  - protocol.py   — 0x38-byte header with magic bytes, checksums at 0x20/0x34
"""

from .device import BroadlinkDevice
from .crypto import AESCipher, broadlink_encrypt, broadlink_decrypt, derive_device_key
from .protocol import (
    build_device_command,
    parse_device_response,
    build_discovery_packet,
    parse_discovery_response,
    AES_IV,
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
    "AES_IV",
]
