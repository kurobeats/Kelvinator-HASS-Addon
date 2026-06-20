"""
Broadlink DNA SDK Protocol Module
===================================
Implements the Broadlink device protocol packet format and discovery mechanism.

Broadlink device packet structure (80 bytes header + variable payload):
  Offset  Size  Description
  ------  ----  -----------
  0x00    2     Little-endian payload length (with checksum)
  0x02    2     Unused (0x0000)
  0x04    4     Device type (little-endian)
  0x08    2     Packet type/command
  0x0A    2     Packet count
  0x0C    4     Device ID (little-endian)
  0x10    8     MAC address (6 bytes MAC + 2 bytes padding)
  0x18    4     Device ID (copy)
  0x1C    4     Timestamp or sequence
  0x20    4     Reserved / flags
  0x24    4     Reserved
  0x28    4     Reserved
  0x2C    4     Reserved
  0x30    16    Encrypted payload (variable)
"""

import struct
import socket
import time
import random


# Packet type constants
CMD_DISCOVERY = 0x6A
CMD_AUTH = 0x65
CMD_LOGIN = 0x03
CMD_DEVICE_INFO = 0x06
CMD_DEVICE_CONTROL = 0x6A
CMD_DEVICE_STATUS = 0x6B

# Device type constants (from the reverse-engineered binary)
DEV_TYPE_SP1 = 0x0000       # Smart Plug SP1
DEV_TYPE_SP2 = 0x2711       # Smart Plug SP2
DEV_TYPE_SP3 = 0x947A       # Smart Plug SP3
DEV_TYPE_SP3S = 0x9479      # Smart Plug SP3S
DEV_TYPE_SP4L = 0x2222      # Smart Plug SP4L
DEV_TYPE_RM2 = 0x2712       # RM2 IR Controller
DEV_TYPE_RM4 = 0x51DA       # RM4 IR/RF Controller
DEV_TYPE_RM_MINI = 0x2737   # RM Mini IR Controller
DEV_TYPE_A1 = 0x2714        # A1 Environmental Sensor
DEV_TYPE_MP1 = 0x4EB5       # MP1 Power Strip
DEV_TYPE_SC1 = 0x4EAD       # SC1 Smart Switch
DEV_TYPE_HYSEN = 0x4EAF     # Hysen Thermostat

# Header size
HEADER_SIZE = 0x38  # 56 bytes


def build_device_command(
    device_id: int,
    device_type: int,
    device_mac: bytes,
    device_key: bytes,
    command: int,
    payload: bytes,
    count: int = 0,
    iv: bytes = None,
) -> bytes:
    """
    Build a complete Broadlink device command packet.

    Args:
        device_id: 4-byte device ID
        device_type: Device type identifier
        device_mac: 6-byte MAC address
        device_key: 16-byte AES key
        command: Command byte
        payload: Raw command payload
        count: Packet sequence number
        iv: Initialization vector (defaults to derived device IV)

    Returns:
        Complete encrypted packet ready for UDP transmission
    """
    from .crypto import broadlink_encrypt, derive_device_key

    if iv is None:
        iv = derive_device_key(device_id, device_key)

    # Encrypt the payload (adds 2-byte checksum, pads, encrypts)
    encrypted = broadlink_encrypt(payload, device_key, iv)

    pkt_len = len(encrypted)

    # Build the header
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<H", header, 0x00, pkt_len)          # Length
    struct.pack_into("<I", header, 0x04, device_type)       # Device type
    struct.pack_into("<H", header, 0x08, command)           # Command
    struct.pack_into("<H", header, 0x0A, count & 0xFFFF)   # Count
    struct.pack_into("<I", header, 0x0C, device_id)         # Device ID

    # MAC address (6 bytes)
    mac_padded = device_mac[:6].ljust(6, b'\x00')
    header[0x10:0x16] = mac_padded
    # Padding
    header[0x16:0x18] = b'\x00\x00'

    struct.pack_into("<I", header, 0x18, device_id)          # Device ID copy
    struct.pack_into("<I", header, 0x1C, int(time.time()))   # Timestamp
    struct.pack_into("<I", header, 0x20, 0)                  # Reserved
    struct.pack_into("<I", header, 0x24, 0)                  # Reserved
    struct.pack_into("<I", header, 0x28, 0)                  # Reserved
    struct.pack_into("<I", header, 0x2C, 0)                  # Reserved

    return bytes(header) + encrypted


def parse_device_response(
    data: bytes,
    device_key: bytes,
    device_id: int,
    iv: bytes = None,
) -> dict:
    """
    Parse a device response packet.

    Returns:
        Dictionary with header fields and decrypted payload.
    """
    from .crypto import broadlink_decrypt, derive_device_key

    if len(data) < HEADER_SIZE:
        raise ValueError(f"Packet too short: {len(data)} bytes")

    if iv is None:
        iv = derive_device_key(device_id, device_key)

    header = data[:HEADER_SIZE]
    encrypted = data[HEADER_SIZE:]

    pkt_len = struct.unpack_from("<H", header, 0x00)[0]
    device_type = struct.unpack_from("<I", header, 0x04)[0]
    command = struct.unpack_from("<H", header, 0x08)[0]
    count = struct.unpack_from("<H", header, 0x0A)[0]
    dev_id = struct.unpack_from("<I", header, 0x0C)[0]
    mac = header[0x10:0x16]
    timestamp = struct.unpack_from("<I", header, 0x1C)[0]

    payload = broadlink_decrypt(encrypted, device_key, iv)

    return {
        "device_id": dev_id,
        "device_type": device_type,
        "command": command,
        "count": count,
        "mac": mac,
        "timestamp": timestamp,
        "payload": payload,
    }


def build_discovery_packet(
    local_ip: str = None,
    source_port: int = 0,
) -> bytes:
    """
    Build a device discovery/broadcast packet.

    Broadlink devices listen on UDP port 80 and respond to discovery packets
    containing a specific magic pattern.

    Format:
    Offset  Size  Description
    0x00    4     System time (little-endian u32)
    0x04    4     Local IP as u32 (e.g. 192.168.1.100)
    0x08    2     Source port
    ...     ...   Zero-padded to 48 bytes
    """
    pkt = bytearray(48)

    # Current time
    struct.pack_into("<I", pkt, 0x00, int(time.time()))

    # Local IP address
    if local_ip:
        parts = local_ip.split(".")
        ip_int = (int(parts[0]) << 24) | (int(parts[1]) << 16) | \
                 (int(parts[2]) << 8) | int(parts[3])
        struct.pack_into("<I", pkt, 0x04, ip_int)
    else:
        # Use 0.0.0.0
        struct.pack_into("<I", pkt, 0x04, 0)

    # Source port
    struct.pack_into("<H", pkt, 0x08, source_port & 0xFFFF)

    return bytes(pkt)


def parse_discovery_response(data: bytes) -> dict:
    """
    Parse a device discovery response.

    The response includes device type, MAC, IP, and device ID in plaintext.

    Format:
    Offset  Size  Description
    0x00    2     Packet length (little-endian)
    0x02    2     Unknown
    0x04    4     Device type
    0x08    2     Command (0x6A for discovery)
    0x0A    2     Packet count
    0x0C    4     Device ID
    0x10    6     MAC address
    0x18    4     Device ID copy
    0x1C    4     IP address (u32)
    0x20    4     Unknown
    """
    if len(data) < 0x30:
        raise ValueError(f"Discovery response too short: {len(data)} bytes")

    pkt_len = struct.unpack_from("<H", data, 0x00)[0]
    device_type = struct.unpack_from("<I", data, 0x04)[0]
    command = struct.unpack_from("<H", data, 0x08)[0]
    device_id = struct.unpack_from("<I", data, 0x0C)[0]
    mac = data[0x10:0x16]
    # Read the 4 raw bytes at offset 0x1C as IP address (network byte order)
    ip_bytes = data[0x1C:0x20]
    ip = ".".join(str(b) for b in ip_bytes)
    mac_str = ":".join(f"{b:02x}" for b in mac[:6])

    return {
        "device_id": device_id,
        "device_type": device_type,
        "command": command,
        "mac": mac,
        "mac_str": mac_str,
        "ip": ip,
        "raw": data,
    }
