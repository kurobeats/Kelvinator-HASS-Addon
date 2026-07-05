"""
Device: High-level interface for controlling a Kelvinator AC unit.

Uses the reverse-engineered broadlink_api (libNetworkAPI.so protocol)
for transport, encryption, and authentication, and builds AC-specific
TFB payloads on top.

Usage:
    from kelvinator_dna.device import KelvinatorDevice, discover_devices
    from kelvinator_dna.commands import ACMode, FanSpeed, SwingMode, ACState

    dev = KelvinatorDevice(
        ip="192.168.1.100",
        did="00000000000000000000a1b2c3d4e5f6",
        mac="a1:b2:c3:d4:e5:f6",
        aes_key="00112233445566778899aabbccddeeff",
        password=100000001,
    )

    with dev:
        status = dev.get_status()
        print(status)

        state = ACState(
            power=True, mode=ACMode.COOL, temp=22,
            fan=FanSpeed.AUTO, swing=SwingMode.BOTH,
        )
        dev.set_state(state)
"""

import struct
import socket
import time
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from ..broadlink_api.device import BroadlinkDevice
from ..broadlink_api.protocol import (
    CMD_DEVICE_CONTROL,
    CMD_DEVICE_STATUS,
    CMD_AUTH,
)
from ..broadlink_api.crypto import derive_device_key
from .protocol import (
    build_control_payload,
    parse_status_payload,
    AC_DEVTYPE,
)
from .commands import ACState

logger = logging.getLogger(__name__)

# Default network settings
UDP_TIMEOUT = 5.0
DISCOVERY_PORT = 80


@dataclass
class DeviceStatus:
    """Current state of the AC unit."""
    power: bool = False
    mode: int = 0           # 0=cool, 1=heat, 2=dry, 3=fan, 4=auto
    temp: int = 24
    fan: int = 0            # 0=auto, 1=low, 2=med, 3=high, 4=turbo, 5=quiet, 6=low_med, 7=med_high
    swing: int = 0          # 0=off, 1=vert, 2=horiz, 3=both
    sleep: bool = False
    turbo: bool = False
    screen_display: bool = True
    room_temp: Optional[int] = None
    error_code: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        mode_names = {0: "COOL", 1: "HEAT", 2: "DRY", 3: "FAN", 4: "AUTO"}
        fan_names = {0: "AUTO", 1: "LOW", 2: "MED", 3: "HIGH", 4: "TURBO", 5: "QUIET", 6: "LOW_MED", 7: "MED_HIGH"}
        swing_names = {0: "OFF", 1: "VERT", 2: "HORIZ", 3: "BOTH"}

        parts = [
            f"power={'ON' if self.power else 'OFF'}",
            f"mode={mode_names.get(self.mode, str(self.mode))}",
            f"temp={self.temp}°C",
            f"fan={fan_names.get(self.fan, str(self.fan))}",
            f"swing={swing_names.get(self.swing, str(self.swing))}",
        ]
        if self.room_temp is not None:
            parts.append(f"room={self.room_temp}°C")
        if self.sleep:
            parts.append("sleep=ON")
        if self.turbo:
            parts.append("turbo=ON")
        if not self.screen_display:
            parts.append("display=OFF")
        return f"DeviceStatus({', '.join(parts)})"


class KelvinatorDevice:
    """
    Represents a single Kelvinator/Electrolux AC unit on the local network.

    Wraps BroadlinkDevice from broadlink_api for:
      - UDP transport with 0x38-byte DNA header
      - AES-128-CBC encryption with checksum
      - Device authentication (CMD_AUTH handshake)

    Adds AC-specific TFB payload building/parsing on top.
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
        self.did = did.lower()
        self._mac_str = mac.lower()
        self.aes_key = aes_key.lower()
        self.password = password
        self.port = port
        self.timeout = timeout

        # Parse MAC to bytes
        self._mac = bytes.fromhex(self._mac_str.replace(':', ''))

        # Parse AES key
        self._key = bytes.fromhex(self.aes_key)

        # Create the underlying Broadlink device.
        # device_id is initially 0 — it is set during auth().
        self._bldev = BroadlinkDevice(
            host=self.ip,
            mac=self._mac,
            device_type=AC_DEVTYPE,
            device_id=0,
            key=self._key,
            timeout=self.timeout,
        )

        self._pending_params: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Authenticate with the device, then install the cloud key."""
        if self._bldev._authenticated:
            return
        if not self._bldev.auth():
            # Do NOT pretend authentication succeeded.  The previous code
            # set _authenticated=True on failure, which then sent commands
            # with device_id=0 and the wrong key -> errno -6 / empty
            # responses.  Fail loudly instead.
            raise RuntimeError(
                f"Device authentication failed for {self.ip} ({self._mac_str})"
            )
        # After auth, the device_id is obtained from the handshake.
        # Replace the session key with our per-device cloud key
        # (this is what the official Electrolux app does).
        self._bldev.update_key(self._key)
        logger.info(
            "Connected & authenticated: device_id=0x%08x",
            self._bldev.device_id,
        )

    def disconnect(self) -> None:
        """Reset authentication state."""
        self._bldev._authenticated = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level send/receive (delegates to BroadlinkDevice)
    # ------------------------------------------------------------------

    def _send_and_receive(self, command: int, payload: bytes) -> bytes:
        """
        Send a command payload and receive the decrypted response payload.

        Both control (TFB command_type=0x01) and status query (0x02) are sent
        with Broadlink command byte 0x6A; the TFB ``command_type`` field
        inside the payload distinguishes them.  The payload built by the
        caller (build_control_payload) MUST be forwarded unchanged — the
        previous get_status() call discarded it and sent b'\x00'.
        """
        if command == CMD_DEVICE_STATUS:
            result = self._bldev.get_status(payload)
        else:
            result = self._bldev.send_command(payload)
        return result.get("payload", b"")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> DeviceStatus:
        """Query the current AC state from the device."""
        params = {
            'did': self.did,
            'sub_device_id': 0,
            'command_type': 0x02,  # Query status
        }
        payload = build_control_payload(params)
        resp = self._send_and_receive(CMD_DEVICE_STATUS, payload)
        status_data = parse_status_payload(resp)

        status = DeviceStatus(
            power=status_data.get('power', False),
            mode=status_data.get('mode', 0),
            temp=status_data.get('temp', 24),
            fan=status_data.get('fan', 0),
            swing=status_data.get('swing', 0),
            sleep=status_data.get('sleep', False),
            turbo=status_data.get('turbo', False),
            screen_display=status_data.get('screen_display', True),
            room_temp=status_data.get('room_temp'),
            error_code=status_data.get('error_code', 0),
            raw=status_data,
        )
        logger.info("Status: %s", status)
        return status

    # ------------------------------------------------------------------
    # State-based control (set all at once)
    # ------------------------------------------------------------------

    def set_state(self, state: ACState) -> None:
        """Apply a complete AC state in a single command."""
        params = {
            'did': self.did,
            'sub_device_id': 0,
            'command_type': 0x01,  # Set control
            **state.to_dict(),
        }
        payload = build_control_payload(params)
        resp = self._send_and_receive(CMD_DEVICE_CONTROL, payload)
        logger.info("State set: %s, response %d bytes", state, len(resp))

    # ------------------------------------------------------------------
    # Individual parameter setters
    # ------------------------------------------------------------------

    def set_power(self, on: bool) -> None:
        self._pending_params['power'] = on

    def set_mode(self, mode: int) -> None:
        self._pending_params['mode'] = mode

    def set_temperature(self, temp: int) -> None:
        if not (16 <= temp <= 30):
            raise ValueError(f"Temperature {temp}°C outside range 16-30")
        self._pending_params['temp'] = temp

    def set_fan_speed(self, speed: int) -> None:
        self._pending_params['fan'] = speed

    def set_swing(self, swing: int) -> None:
        self._pending_params['swing'] = swing

    def set_sleep(self, enabled: bool) -> None:
        self._pending_params['sleep'] = enabled

    def set_turbo(self, enabled: bool) -> None:
        self._pending_params['turbo'] = enabled

    def set_screen_display(self, enabled: bool) -> None:
        self._pending_params['screen_display'] = enabled

    def send_control(self) -> None:
        """Send accumulated individual parameter changes to the device."""
        if not self._pending_params:
            logger.warning("No pending parameters to send")
            return

        params = {
            'did': self.did,
            'sub_device_id': 0,
            'command_type': 0x01,
            **self._pending_params,
        }
        payload = build_control_payload(params)
        resp = self._send_and_receive(CMD_DEVICE_CONTROL, payload)
        logger.info("Control sent: %d bytes response", len(resp))
        self._pending_params.clear()

    # ------------------------------------------------------------------
    # Discovery (classmethod + module-level)
    # ------------------------------------------------------------------

    @classmethod
    def discover(
        cls,
        broadcast_ip: str = "255.255.255.255",
        port: int = 80,
        timeout: float = 3.0,
    ) -> List[Dict[str, str]]:
        """Discover Kelvinator AC devices on the local network."""
        return discover_devices(broadcast_ip, port, timeout)


# ------------------------------------------------------------------
# Module-level discovery using broadlink_api
# ------------------------------------------------------------------

def discover_devices(
    broadcast_ip: str = "255.255.255.255",
    port: int = 80,
    timeout: float = 3.0,
) -> List[Dict[str, str]]:
    """
    Discover Kelvinator AC devices on the local network.

    Uses broadlink_api's discovery mechanism (48-byte UDP broadcast).
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
            'ip': info.get('ip', addr[0]),
            'mac': info.get('mac_str', ''),
            'did': hex(info.get('device_id', 0)),
            'name': info.get('name', ''),
        })
        logger.info(
            "Discovered: %s at %s (%s)",
            info.get('device_id', '?'), info.get('ip', '?'), info.get('mac_str', '?'),
        )

    sock.close()
    return devices
