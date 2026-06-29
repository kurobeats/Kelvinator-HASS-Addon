"""
Broadlink DNA SDK Protocol Module
===================================
Corrected implementation matching the python-broadlink library and real
device traffic observed from the official Kelvinator Android app.

Broadlink device packet structure (0x38-byte header + variable payload):

  Offset  Size  Description
  ------  ----  -----------
  0x00     8    Magic bytes (5A A5 AA 55 5A A5 AA 55)
  0x08     8    (unused / firmware-specific)
  0x10     4    (unused)
  0x14     4    (unused)
  0x18     4    (unused)
  0x1C     4    (unused)
  0x20     2    Header checksum  -- sum(header, 0xBEAF) & 0xFFFF
  0x22     2    Error status field on responses
  0x24     2    Device type (little-endian)
  0x26     2    Packet type / command (little-endian)
  0x28     2    Sequence counter (little-endian, bit 15 set)
  0x2A     6    MAC address (reversed byte order)
  0x30     4    Device ID (little-endian)
  0x34     2    Payload checksum -- sum(payload, 0xBEAF) & 0xFFFF
  0x36     2    (padding)
  0x38    ...   AES-128-CBC encrypted payload (zero-padded to 16-byte boundary)

Encryption:
  - AES-128-CBC with a hardcoded IV (562e17996d093d28ddb3ba695a2e6f58)
  - Key: either the BroadLink default key or the per-device cloud key
  - Padding: zero bytes (NOT PKCS7)
  - Payload checksum is computed BEFORE encryption
  - Header checksum covers header fields only (before appending encrypted payload)

Discovery:
  - 0x30-byte broadcast packet on UDP port 80
  - Response includes device type, MAC, IP, firmware version
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

# Header size
HEADER_SIZE = 0x38  # 56 bytes

# AES IV (hardcoded for all BroadLink devices)
AES_IV = bytes.fromhex("562e17996d093d28ddb3ba695a2e6f58")


def build_device_command(
    device_id: int,
    device_type: int,
    device_mac: bytes,
    device_key: bytes,
    command: int,
    payload: bytes,
    count: int = 0,
) -> bytes:
    """
    Build a complete Broadlink device command packet.

    Matches the python-broadlink library's send_packet() exactly.

    Args:
        device_id: 4-byte device ID (from auth or DID)
        device_type: Device type identifier (e.g. 0x4F9B)
        device_mac: 6-byte MAC address
        device_key: 16-byte AES key
        command: Command byte (0x6A = device_control, 0x65 = auth, etc.)
        payload: Raw command payload (unencrypted)
        count: Packet sequence number (bit 15 must be set)

    Returns:
        Complete encrypted packet ready for UDP transmission
    """
    from .crypto import AESCipher

    # Build header
    header = bytearray(HEADER_SIZE)

    # Magic bytes
    header[0x00:0x08] = bytes.fromhex("5aa5aa555aa5aa55")

    # Device type (2 bytes LE)
    struct.pack_into("<H", header, 0x24, device_type & 0xFFFF)

    # Packet type / command (2 bytes LE)
    struct.pack_into("<H", header, 0x26, command & 0xFFFF)

    # Sequence counter (bit 15 set)
    count = (count | 0x8000) & 0xFFFF
    struct.pack_into("<H", header, 0x28, count)

    # MAC address (6 bytes, reversed)
    mac_rev = bytes(reversed(device_mac[:6]))
    header[0x2A:0x30] = mac_rev.ljust(6, b'\x00')[:6]

    # Device ID (4 bytes LE)
    struct.pack_into("<I", header, 0x30, device_id & 0xFFFFFFFF)

    # Payload checksum
    p_checksum = (sum(payload, 0xBEAF)) & 0xFFFF
    struct.pack_into("<H", header, 0x34, p_checksum)

    # Encrypt payload with zero-padding
    padding_len = (16 - (len(payload) % 16)) % 16
    padded = payload + bytes(padding_len)
    cipher = AESCipher(device_key, iv=AES_IV)
    encrypted_payload = cipher.encrypt(padded)

    # Assemble: header + encrypted payload
    packet = bytes(header) + encrypted_payload

    # Header checksum (covers header only, NOT the payload)
    h_checksum = (sum(header, 0xBEAF)) & 0xFFFF
    packet = bytearray(packet)
    struct.pack_into("<H", packet, 0x20, h_checksum)

    return bytes(packet)


def parse_device_response(
    data: bytes,
    device_key: bytes,
) -> dict:
    """
    Parse a device response packet.

    Matches the python-broadlink library: the response is returned RAW by
    send_packet().  The caller must decrypt the payload at data[0x38:]
    separately.

    Returns:
        Dictionary with header fields.  'encrypted_payload' contains
        the raw encrypted bytes at data[0x38:].
    """
    from .crypto import AESCipher

    if len(data) < HEADER_SIZE:
        raise ValueError(f"Packet too short: {len(data)} bytes")

    device_type = struct.unpack_from("<H", data, 0x24)[0]
    command = struct.unpack_from("<H", data, 0x26)[0]
    count = struct.unpack_from("<H", data, 0x28)[0]
    dev_id = struct.unpack_from("<I", data, 0x30)[0]
    mac_rev = data[0x2A:0x30]
    mac = bytes(reversed(mac_rev[:6]))
    error_code = struct.unpack_from("<h", data, 0x22)[0]

    encrypted_payload = data[HEADER_SIZE:]

    # Decrypt the payload
    cipher = AESCipher(device_key, iv=AES_IV)
    decrypted = cipher.decrypt(encrypted_payload)
    # Strip zero-padding
    payload = decrypted.rstrip(b'\x00')

    return {
        "device_id": dev_id,
        "device_type": device_type,
        "command": command,
        "count": count,
        "mac": mac,
        "error_code": error_code,
        "payload": payload,
    }


def build_discovery_packet(
    local_ip: str = None,
    source_port: int = 0,
) -> bytes:
    """
    Build a device discovery/broadcast packet (0x30 bytes).

    Matches the python-broadlink library's scan() packet format.

    Format (0x30 bytes):
      0x00:    4    (unused / zero)
      0x04:    4    (unused / zero)
      0x08:   12    Datetime packed (year, seconds, minutes, hours, weekday, day, month)
      0x14:    4    (unused / zero)
      0x18:    4    Local IP address (bytes in network order)
      0x1C:    2    Source port (LE)
      0x1E:    2    (unused / zero)
      0x20:    2    Header checksum
      0x22:    2    (unused / zero)
      0x24:    2    (unused / zero)
      0x26:    1    Flag byte (6 = discover, 1 = ping)
      0x27:    9    (unused / zero)
    """
    pkt = bytearray(0x30)

    # Datetime at offset 0x08 (matching python-broadlink Datetime.pack)
    now = time.localtime()
    struct.pack_into(
        "<HBBBBBB", pkt, 0x08,
        now.tm_year, now.tm_sec, now.tm_min, now.tm_hour,
        now.tm_wday + 1, now.tm_mday, now.tm_mon,
    )

    # Local IP
    if local_ip:
        parts = local_ip.split(".")
        ip_bytes = bytes([int(p) for p in parts])
        pkt[0x18:0x1C] = ip_bytes[::-1]  # reversed byte order
    else:
        pkt[0x18:0x1C] = b'\x00\x00\x00\x00'

    # Source port
    struct.pack_into("<H", pkt, 0x1C, source_port & 0xFFFF)

    # Flag byte: 0x06 for discovery
    pkt[0x26] = 0x06

    # Header checksum
    checksum = (sum(pkt, 0xBEAF)) & 0xFFFF
    struct.pack_into("<H", pkt, 0x20, checksum)

    return bytes(pkt)


def parse_discovery_response(data: bytes) -> dict:
    """
    Parse a device discovery/hello response.

    Matches python-broadlink's scan() response format (0x30+ bytes).

    Returns:
        Dict with device_id, device_type, mac, mac_str, ip, name, is_locked.
    """
    if len(data) < 0x30:
        raise ValueError(f"Discovery response too short: {len(data)} bytes")

    device_type = struct.unpack_from("<H", data, 0x34)[0]
    mac_rev = data[0x3A:0x40]
    mac = bytes(reversed(mac_rev[:6]))
    mac_str = ":".join(f"{b:02x}" for b in mac)

    # IP address at 0x3A? Actually, the hello response embeds IP differently.
    # The scan() function parses host from the UDP packet source address.
    # For completeness, try to parse name and is_locked from the response.
    raw_name = data[0x40:].split(b"\x00")[0]
    try:
        name = raw_name.decode("utf-8")
    except UnicodeDecodeError:
        name = raw_name.decode("latin-1", errors="replace")

    is_locked = bool(data[0x7F]) if len(data) > 0x7F else False

    return {
        "device_type": device_type,
        "mac": mac,
        "mac_str": mac_str,
        "name": name,
        "is_locked": is_locked,
        "raw": data,
    }
