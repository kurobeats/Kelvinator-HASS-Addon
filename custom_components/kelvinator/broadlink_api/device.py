"""
Broadlink Device Module
=========================
High-level representation of a Broadlink smart home device.

Provides discovery, authentication, and control operations matching
the API surface of the original libNetworkAPI.so JNI library.
"""

import json
import struct
import socket
import time
from typing import Optional, Dict, List, Any

from .protocol import (
    build_device_command,
    parse_device_response,
    build_discovery_packet,
    parse_discovery_response,
    CMD_AUTH,
    CMD_LOGIN,
    CMD_DEVICE_CONTROL,
    CMD_DEVICE_STATUS,
    CMD_DISCOVERY,
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
            device_type: Device type identifier
            device_id: Device ID (can be 0; obtained during auth)
            key: 16-byte AES key (default is the Broadlink default key)
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.mac = mac[:6] if len(mac) > 6 else mac.ljust(6, b'\x00')
        self.device_type = device_type
        self.device_id = device_id
        self.key = key if key else self._default_key()
        self.timeout = timeout
        self.iv = None
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
        """Get and increment the packet sequence counter."""
        self._count = (self._count + 1) & 0xFFFF
        return self._count

    def _send_packet(self, command: int, payload: bytes) -> bytes:
        """
        Send a command packet and receive the response.

        Returns the raw response bytes.
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
                iv=self.iv,
            )
            sock.sendto(pkt, (self.host, DEVICE_PORT))
            data, addr = sock.recvfrom(4096)
            return data
        finally:
            sock.close()

    def auth(self) -> bool:
        """
        Authenticate with the device.

        The Broadlink auth handshake:
        1. Send an empty auth command (0x65)
        2. Receive an encrypted response with the device ID and key
        3. Derive the IV from device ID + key

        Returns:
            True if authentication succeeded.
        """
        # Step 1: Send auth request
        response = self._send_packet(CMD_AUTH, b'\x00' * 80)

        if len(response) < 0x38:
            return False

        # Extract device ID from response header
        dev_id = struct.unpack_from("<I", response, 0x0C)[0]
        self.device_id = dev_id

        # Derive IV
        self.iv = derive_device_key(self.device_id, self.key)
        self._authenticated = True
        return True

    def get_device_info(self) -> Dict[str, Any]:
        """
        Get device information (name, type, firmware version, etc.).

        Corresponds to `networkapi_device_profile` in the native library.
        """
        if not self._authenticated:
            self.auth()

        payload = struct.pack("<I", 1)  # Request sub-command 1 for info
        response = self._send_packet(CMD_DEVICE_STATUS, payload)

        result = parse_device_response(response, self.key, self.device_id, self.iv)
        return self._parse_device_info(result["payload"])

    def _parse_device_info(self, payload: bytes) -> Dict[str, Any]:
        """Parse the device info from the raw payload."""
        info = {
            "device_id": self.device_id,
            "device_type": hex(self.device_type),
        }
        try:
            # Device name is at offset 0x40, typically null-terminated ASCII
            null_idx = payload.find(b'\x00', 0x40)
            if null_idx > 0x40:
                info["name"] = payload[0x40:null_idx].decode("utf-8", errors="replace")

            # MAC at some offset
            info["mac"] = ":".join(f"{b:02x}" for b in self.mac[:6])

            # Firmware info may be embedded
        except Exception:
            pass
        return info

    def send_command(self, command_data: bytes) -> Dict[str, Any]:
        """
        Send an arbitrary device control command.

        Corresponds to `networkapi_dna_control` / `network_device_remote_control`.

        Args:
            command_data: Raw command payload (device-specific)

        Returns:
            Parsed response dictionary with 'payload' key.
        """
        if not self._authenticated:
            self.auth()

        response = self._send_packet(CMD_DEVICE_CONTROL, command_data)
        return parse_device_response(response, self.key, self.device_id, self.iv)

    def set_power(self, state: bool) -> Dict[str, Any]:
        """
        Turn the device on or off (for SP series plugs, MP1, etc.).

        Args:
            state: True for ON, False for OFF
        """
        payload = struct.pack("<I", 1 if state else 0)
        return self.send_command(payload)

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current device status.

        Corresponds to `networkapi_device_devicestatus` / `deviceStatusOnServer`.
        """
        if not self._authenticated:
            self.auth()

        payload = struct.pack("<I", 2)  # Status sub-command
        response = self._send_packet(CMD_DEVICE_STATUS, payload)
        return parse_device_response(response, self.key, self.device_id, self.iv)

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

        Corresponds to `networkapi_device_probe` in the native library.

        Args:
            timeout: How long to wait for responses (seconds)
            local_ip: Local IP to use in the discovery packet

        Returns:
            List of discovered BroadlinkDevice instances.
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
                    host=info["ip"],
                    mac=info["mac"],
                    device_type=info["device_type"],
                    device_id=info["device_id"],
                    key=key,
                    timeout=timeout,
                )
                devices[info["device_id"]] = dev
        finally:
            sock.close()

        return list(devices.values())

    def __repr__(self):
        mac_str = ":".join(f"{b:02x}" for b in self.mac[:6])
        return (
            f"BroadlinkDevice(host={self.host}, mac={mac_str}, "
            f"type=0x{self.device_type:04x}, id=0x{self.device_id:08x})"
        )
