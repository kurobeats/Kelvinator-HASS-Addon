"""
Broadlink Device Module
=========================
High-level representation of a Broadlink smart home device.

Provides discovery, authentication, and control operations using
the Broadlink DNA protocol (matching python-broadlink library format).

For Kelvinator/Electrolux ACs (devtype 0x4F9B), the transport AES key
is replaced with the per-device cloud key after authentication, matching
what the official app does.
"""

import struct
import socket
import time
from typing import Optional, Dict, List, Any

from .protocol import (
    build_device_command,
    parse_device_response,
    build_discovery_packet,
    parse_discovery_response,
    AES_IV,
    CMD_AUTH,
    CMD_DEVICE_CONTROL,
    CMD_DEVICE_STATUS,
)
from .crypto import AESCipher, broadlink_decrypt, derive_device_key


# Default ports
DISCOVERY_PORT = 80
DEVICE_PORT = 80


class BroadlinkDevice:
    """
    Represents a single Broadlink smart home device.

    Handles discovery, authentication, and device control commands
    using the Broadlink DNA protocol.
    """

    def __init__(
        self,
        host: str,
        mac: bytes,
        device_type: int,
        device_id: int = 0,
        key: bytes = None,
        timeout: float = 5.0,
    ):
        """
        Initialize a Broadlink device.

        Args:
            host: IP address of the device
            mac: 6-byte MAC address
            device_type: Device type identifier (e.g. 0x4F9B for Kelvinator AC)
            device_id: Device ID (0 = obtained during auth)
            key: 16-byte AES key (the per-device cloud key for Kelvinator)
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.mac = mac[:6] if len(mac) > 6 else mac.ljust(6, b'\x00')
        self.device_type = device_type
        self.device_id = device_id
        self.key = key if key else self._default_key()
        self.timeout = timeout
        self._count = 0
        self._authenticated = False
        self._sock = None

    @staticmethod
    def _default_key() -> bytes:
        """Broadlink default AES key for most devices."""
        return bytes([
            0x09, 0x76, 0x28, 0x34, 0x3F, 0xE9, 0x9E, 0x23,
            0x76, 0x5C, 0x15, 0x13, 0xAC, 0xCF, 0x8B, 0x02,
        ])

    def _get_count(self) -> int:
        """Get and increment the packet sequence counter (bit 15 set)."""
        self._count = ((self._count + 1) | 0x8000) & 0xFFFF
        return self._count

    def _send_packet(self, command: int, payload: bytes) -> bytes:
        """
        Send a command packet and receive the raw response.

        The response is returned RAW (NOT decrypted).  The caller must
        decrypt the payload at data[0x38:] using the device key.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)

        try:
            pkt = build_device_command(
                device_id=self.device_id,
                device_type=self.device_type,
                device_mac=self.mac,
                device_key=self.key,
                command=command,
                payload=payload,
                count=self._get_count(),
            )
            sock.sendto(pkt, (self.host, DEVICE_PORT))
            data, addr = sock.recvfrom(4096)
            return data
        finally:
            sock.close()

    def auth(self) -> bool:
        """
        Authenticate with the device.

        The Broadlink auth handshake (matching python-broadlink):
        1. Send auth command (0x65) with magic payload
        2. Receive response with device ID and session key
        3. Update AES key with the session key

        For Kelvinator ACs, the caller should then overwrite the key
        with the per-device cloud key via update_key().

        Returns:
            True if authentication succeeded.
        """
        # Build auth payload (matches python-broadlink's auth())
        packet = bytearray(0x50)
        packet[0x04:0x14] = bytes([0x31] * 16)
        packet[0x1E] = 0x01
        packet[0x2D] = 0x01
        packet[0x30:0x36] = b"Test 1"

        response = self._send_packet(CMD_AUTH, packet)

        if len(response) < 0x38:
            return False

        # Decrypt response payload with current (default) key
        decrypted = broadlink_decrypt(response[0x38:], self.key, AES_IV)

        # Extract device ID (first 4 bytes) and session key (next 16 bytes)
        self.device_id = int.from_bytes(decrypted[:0x4], "little")
        session_key = decrypted[0x04:0x14]

        # Update AES key to the session key
        self.key = session_key
        self._authenticated = True
        return True

    def update_key(self, new_key: bytes) -> None:
        """Replace the device AES key (e.g. with the per-device cloud key)."""
        if len(new_key) != 16:
            raise ValueError(f"Key must be 16 bytes, got {len(new_key)}")
        self.key = new_key

    def send_command(self, command_data: bytes) -> Dict[str, Any]:
        """
        Send an arbitrary device control command (0x6A).

        Args:
            command_data: Raw unencrypted command payload

        Returns:
            Parsed response dictionary with 'payload' key.
        """
        if not self._authenticated:
            self.auth()

        response = self._send_packet(CMD_DEVICE_CONTROL, command_data)
        return parse_device_response(response, self.key)

    def get_status(self) -> Dict[str, Any]:
        """
        Query device status (0x6B).

        Returns:
            Parsed response dictionary with 'payload' key.
        """
        if not self._authenticated:
            self.auth()

        response = self._send_packet(CMD_DEVICE_STATUS, b'\x00')
        return parse_device_response(response, self.key)

    @classmethod
    def discover(
        cls,
        timeout: float = 5.0,
        local_ip: str = None,
        key: bytes = None,
    ) -> List["BroadlinkDevice"]:
        """
        Discover Broadlink devices on the local network.

        Sends a broadcast discovery packet and collects responses.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)

        devices = {}
        pkt = build_discovery_packet(local_ip=local_ip)

        try:
            sock.sendto(pkt, ("255.255.255.255", DISCOVERY_PORT))

            start = time.time()
            while time.time() - start < timeout:
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    break

                try:
                    info = parse_discovery_response(data)
                except ValueError:
                    continue

                dev = cls(
                    host=addr[0],
                    mac=info["mac"],
                    device_type=info["device_type"],
                    key=key,
                    timeout=timeout,
                )
                devices[info["mac"].hex()] = dev
        finally:
            sock.close()

        return list(devices.values())

    def __repr__(self):
        mac_str = ":".join(f"{b:02x}" for b in self.mac[:6])
        return (
            f"BroadlinkDevice(host={self.host}, mac={mac_str}, "
            f"type=0x{self.device_type:04x}, id=0x{self.device_id:08x})"
        )
