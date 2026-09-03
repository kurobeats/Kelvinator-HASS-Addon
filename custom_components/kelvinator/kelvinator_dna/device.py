"""
Device: High-level interface for controlling a Kelvinator AC unit.

Uses broadlink_api for the transport layer (UDP, 0x38 Broadlink DNA
header, AES-128-CBC) and the DNA Kit payload format (see protocol.py)
discovered from the bundled DNA Kit Lua script.

NOTE: these Kelvinator ACs are *locked* DNA devices — raw local UDP auth
(CMD_AUTH 0x65) is rejected with errno -7 ("control key is expired")
because the device only accepts session keys issued via the cloud SDKAuth
(ECDH) handshake.  The official app performs SDKAuth first; until that is
reimplemented (or the bundled native SDK bridge is used, see
dna_native.py), this local path will fail with -7.

Usage:
    from kelvinator_dna.device import KelvinatorDevice
    from kelvinator_dna.commands import ACState, ACMode, FanSpeed

    dev = KelvinatorDevice(
        ip="192.168.1.100",
        did="00000000000000000000a1b2c3d4e5f6",
        mac="a1:b2:c3:d4:e5:f6",
        aes_key="00112233445566778899aabbccddeeff",
        password=0,
    )

    with dev:
        status = dev.get_status()
        print(status)

        dev.set_state(ACState(power=True, mode=ACMode.COOL, temp=22))
"""

import json
import logging
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..broadlink_api.device import BroadlinkDevice
from ..broadlink_api.protocol import (
    CMD_DEVICE_CONTROL,
    CMD_AUTH,
)
from .protocol import build_payload, parse_payload, parse_values
from .commands import ACState

logger = logging.getLogger(__name__)

UDP_TIMEOUT = 5.0
DISCOVERY_PORT = 80


@dataclass
class DeviceStatus:
    """Current state of the AC unit (DNA Kit param names)."""
    raw: Dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        try:
            return self.raw[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __repr__(self) -> str:
        return f"DeviceStatus({json.dumps(self.raw)})"


class KelvinatorDevice:
    """
    A Kelvinator/Electrolux AC unit on the local network.

    Wraps BroadlinkDevice (UDP transport + AES) and speaks the DNA Kit
    payload protocol.  Requires a cloud-issued session key (see module
    docstring on locked devices).
    """

    def __init__(
        self,
        ip: str,
        did: str,
        mac: str,
        aes_key: str,
        password: int = 0,
        port: int = 80,
        timeout: float = UDP_TIMEOUT,
    ):
        self.ip = ip
        self.did = did
        self._mac_str = mac.lower()
        self.aes_key = aes_key.lower()
        self.password = password
        self.port = port
        self.timeout = timeout

        self._mac = bytes.fromhex(self._mac_str.replace(':', ''))
        self._key = bytes.fromhex(self.aes_key)

        self._bldev = BroadlinkDevice(
            host=self.ip,
            mac=self._mac,
            device_type=0x4F9B,
            device_id=0,
            key=self._key,
            timeout=self.timeout,
        )

    def connect(self) -> None:
        """
        Authenticate with the device.

        Raises RuntimeError with the device's errno on failure.  For these
        locked DNA devices this is expected to fail with errno -7 unless a
        cloud SDKAuth-issued control key is available.
        """
        if not self._bldev.auth():
            raise RuntimeError(
                f"Device authentication failed for {self.ip} ({self._mac_str})"
            )
        # After auth, replace the session key with the per-device cloud key
        # (this is what the official app does after SDKAuth).
        self._bldev.update_key(self._key)
        logger.info(
            "Connected & authenticated: device_id=0x%08x", self._bldev.device_id,
        )

    def disconnect(self) -> None:
        self._bldev._authenticated = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level send/receive
    # ------------------------------------------------------------------

    def _send_and_receive(self, payload: bytes) -> bytes:
        """Send a DNA packet and return the decrypted response payload."""
        result = self._bldev.send_command(payload)
        return result.get("payload", b"")

    # ------------------------------------------------------------------
    # Status / control
    # ------------------------------------------------------------------

    def get_status(self, params: List[str] | None = None) -> DeviceStatus:
        """Query AC state. Returns DNA Kit param values."""
        names = params or [
            "ac_pwr", "ac_mode", "temp", "ac_mark", "ac_vdir", "ac_slp",
            "scrdisp", "ecomode", "envtemp", "ac_errcode",
        ]
        payload = build_payload(self.did, "get", {p: 0 for p in names})
        resp = self._send_and_receive(payload)
        if not resp:
            return DeviceStatus(raw={})
        return DeviceStatus(raw=parse_values(parse_payload(resp)))

    def set_state(self, state: ACState) -> None:
        """Apply a complete AC state in a single command."""
        self.set_params(state.to_dna_params())

    def set_params(self, params: Dict[str, Any]) -> None:
        """Send {dna_param_name: value} to the device."""
        payload = build_payload(self.did, "set", params)
        resp = self._send_and_receive(payload)
        logger.info("Control sent, response %d bytes", len(resp))

    # ------------------------------------------------------------------
    # Convenience setters
    # ------------------------------------------------------------------

    def set_power(self, on: bool) -> None:
        self.set_params({"ac_pwr": int(on)})

    def set_mode(self, mode: int) -> None:
        self.set_params({"ac_mode": mode})

    def set_temperature(self, temp: int) -> None:
        if not (16 <= temp <= 30):
            raise ValueError(f"Temperature {temp}°C outside range 16-30")
        self.set_params({"temp": temp})

    def set_fan_speed(self, speed: int) -> None:
        self.set_params({"ac_mark": speed})

    def set_swing(self, swing: int) -> None:
        self.set_params({"ac_vdir": swing})

    def set_sleep(self, enabled: bool) -> None:
        self.set_params({"ac_slp": int(enabled)})

    def set_screen_display(self, enabled: bool) -> None:
        self.set_params({"scrdisp": int(enabled)})

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @classmethod
    def discover(
        cls,
        broadcast_ip: str = "255.255.255.255",
        port: int = 80,
        timeout: float = 3.0,
    ) -> List[Dict[str, str]]:
        return discover_devices(broadcast_ip, port, timeout)


def discover_devices(
    broadcast_ip: str = "255.255.255.255",
    port: int = 80,
    timeout: float = 3.0,
) -> List[Dict[str, str]]:
    """
    Discover Kelvinator AC devices on the local network.

    Uses broadlink_api's discovery (0x30-byte UDP broadcast).  Note the
    discovery response carries the device_id at header offset 0x30.
    """
    from ..broadlink_api.protocol import (
        build_discovery_packet,
        parse_discovery_response,
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    pkt = build_discovery_packet()
    sock.sendto(pkt, (broadcast_ip, DISCOVERY_PORT))

    devices: List[Dict[str, str]] = []
    start = time.time()

    while time.time() - start < timeout:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            break

        try:
            info = parse_discovery_response(data)
        except (ValueError, struct.error):
            continue

        devices.append({
            'ip': addr[0],
            'mac': info.get('mac_str', ''),
            'device_id': f"0x{int.from_bytes(data[0x30:0x34], 'little'):08x}",
            'name': info.get('name', ''),
        })
        logger.info(
            "Discovered: %s at %s (%s)",
            info.get('mac_str', '?'), addr[0], info.get('device_id', '?'),
        )

    sock.close()
    return devices