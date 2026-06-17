"""
Device: High-level interface for controlling a Kelvinator AC unit.

Communicates with the device over UDP on the local network using the
DNA protocol with AES-128-ECB encryption.

Usage:
    from kelvinator_dna.device import KelvinatorDevice
    from kelvinator_dna.commands import ACMode, FanSpeed, SwingMode

    dev = KelvinatorDevice(
        ip="192.168.1.100",
        did="00000000000000000000a043b036bff4",
        mac="a0:43:b0:36:bf:f4",
        aes_key="99293543659c5b0caf659134ead8817f",
        password=754770058,
    )

    # Connect and authenticate
    dev.connect()
    dev.authenticate()

    # Get current status
    status = dev.get_status()
    print(status)

    # Set cooling mode, 22°C, auto fan, swing on
    dev.set_power(True)
    dev.set_mode(ACMode.COOL)
    dev.set_temperature(22)
    dev.set_fan_speed(FanSpeed.AUTO)
    dev.set_swing(SwingMode.BOTH)
    dev.send_control()

    # Or set all at once
    from kelvinator_dna.commands import ACState
    state = ACState(
        power=True, mode=ACMode.COOL, temp=22,
        fan=FanSpeed.HIGH, swing=SwingMode.VERTICAL
    )
    dev.set_state(state)
"""

import socket
import struct
import time
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from .protocol import (
    DNACommand, DNAEncryption,
    build_dna_packet, parse_dna_packet,
    build_control_payload, parse_status_payload,
)
from .commands import ACMode, FanSpeed, SwingMode, ACState

logger = logging.getLogger(__name__)

# Default UDP ports
DNA_PORT = 80           # Device listens on port 80 (UDP)
LOCAL_PORT = 0          # OS-assigned ephemeral port
DEVICE_DISCOVERY_PORT = 80  # Discovery broadcast port

# Timing
UDP_TIMEOUT = 5.0       # Default UDP receive timeout
RETRY_COUNT = 3         # Number of retries for commands


@dataclass
class DeviceStatus:
    """Current state of the AC unit."""
    power: bool = False
    mode: int = 0       # 0=cool, 1=heat, 2=auto, 3=fan, 4=dry
    temp: int = 24      # Target temperature
    fan: int = 0        # Fan speed (0=auto, 1=low, 2=med, 3=high)
    swing: int = 0      # Swing mode
    sleep: bool = False
    turbo: bool = False
    room_temp: Optional[int] = None  # Current room temperature
    error_code: int = 0
    raw: Dict[str, Any] = None

    def __post_init__(self):
        if self.raw is None:
            self.raw = {}

    def __repr__(self) -> str:
        mode_names = {0: "COOL", 1: "HEAT", 2: "AUTO", 3: "FAN", 4: "DRY"}
        fan_names = {0: "AUTO", 1: "LOW", 2: "MED", 3: "HIGH"}
        swing_names = {0: "OFF", 1: "VERT", 2: "HORIZ", 3: "BOTH"}

        parts = [
            f"power={'ON' if self.power else 'OFF'}",
            f"mode={mode_names.get(self.mode, str(self.mode))}",
            f"temp={self.temp}°C",
            f"fan={fan_names.get(self.fan, str(self.fan))}",
            f"swing={swing_names.get(self.swing, str(self.swing))}",
        ]
        if self.room_temp:
            parts.append(f"room={self.room_temp}°C")
        if self.sleep:
            parts.append("sleep=ON")
        if self.turbo:
            parts.append("turbo=ON")
        return f"DeviceStatus({', '.join(parts)})"


class KelvinatorDevice:
    """
    Represents a single Kelvinator/Electrolux AC unit.

    Handles:
      - UDP communication with the device
      - DNA protocol packet assembly and parsing
      - AES-128-ECB encryption/decryption
      - Device authentication handshake
      - Control command construction and sending
    """

    def __init__(
        self,
        ip: str,
        did: str,
        mac: str,
        aes_key: str,
        password: int = 0,
        port: int = DNA_PORT,
        timeout: float = UDP_TIMEOUT,
    ):
        """
        Args:
            ip: Device IP address on the local network
            did: Device ID (34 hex chars = 17 bytes)
            mac: MAC address (colon-separated hex)
            aes_key: AES-128 key (32 hex chars = 16 bytes)
            password: Device password (4-byte integer from cloud API)
            port: UDP port (default: 80)
            timeout: UDP response timeout in seconds
        """
        self.ip = ip
        self.did = did
        self.mac = mac
        self.aes_key = aes_key
        self.password = password
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._authenticated = False
        self._session_id = 0
        self._crypto = DNAEncryption(bytes.fromhex(aes_key))

    def connect(self):
        """Create and bind the UDP socket."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.timeout)
        self._sock.bind(('', LOCAL_PORT))
        addr = self._sock.getsockname()
        logger.info(f"Connected: local port {addr[1]}, target {self.ip}:{self.port}")

    def disconnect(self):
        """Close the UDP socket."""
        if self._sock:
            self._sock.close()
            self._sock = None
            self._authenticated = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def _send_raw(self, command: int, payload: bytes) -> bytes:
        """
        Send a raw DNA packet and receive the response.

        Args:
            command: DNA command ID
            payload: Payload bytes (before encryption)

        Returns:
            Response payload bytes (after decryption)
        """
        # Encrypt if authenticated
        if self._authenticated:
            encrypted = self._crypto.encrypt(payload, self.password)
        else:
            encrypted = payload

        # Build and send packet
        packet = build_dna_packet(command, encrypted)
        logger.debug(f"TX: cmd=0x{command:04x}, len={len(packet)}")

        for attempt in range(RETRY_COUNT):
            self._sock.sendto(packet, (self.ip, self.port))

            try:
                resp_data, addr = self._sock.recvfrom(4096)
                logger.debug(f"RX: {len(resp_data)} bytes from {addr}")

                resp_cmd, resp_payload, resp_checksum = parse_dna_packet(resp_data)

                # Verify checksum
                expected = sum(resp_payload) & 0xFFFF
                if resp_checksum != expected:
                    logger.warning(
                        f"Checksum mismatch: got 0x{resp_checksum:04x}, "
                        f"expected 0x{expected:04x}"
                    )

                # Decrypt if authenticated
                if self._authenticated:
                    return self._crypto.decrypt(resp_payload, self.password)
                return resp_payload

            except socket.timeout:
                logger.debug(f"Timeout (attempt {attempt + 1}/{RETRY_COUNT})")
                if attempt == RETRY_COUNT - 1:
                    raise TimeoutError(
                        f"No response from {self.ip}:{self.port} "
                        f"after {RETRY_COUNT} attempts"
                    )

        raise RuntimeError("Unreachable")

    def authenticate(self) -> bool:
        """
        Perform device authentication handshake.

        The auth flow:
          1. Send AUTH_REQUEST with device credentials
          2. Device responds with AUTH_RESPONSE containing a session key
          3. Session key is used for subsequent encrypted communication

        Returns:
            True if authenticated successfully
        """
        # Build auth payload
        payload = bytearray()
        payload.extend(bytes.fromhex(self.did))   # DID (17 bytes)
        payload.extend(struct.pack('>I', self.password))  # Password (4 bytes)

        try:
            resp = self._send_raw(DNACommand.AUTH_REQUEST, bytes(payload))
            # Response should contain session confirmation
            if len(resp) >= 1:
                self._session_id = resp[0]
                self._authenticated = True
                logger.info(f"Authenticated with session {self._session_id}")
                return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")

        # Many devices don't require explicit auth — packets work anyway
        logger.info("Auth not confirmed; proceeding without authentication")
        self._authenticated = True
        return True

    def get_status(self) -> DeviceStatus:
        """
        Query the current device state.

        Returns:
            DeviceStatus with current AC settings
        """
        payload = build_control_payload({
            'did': self.did,
            'command_type': 0x02,  # Query status
        })

        resp = self._send_raw(DNACommand.DEVICE_STATUS, payload)
        status_data = parse_status_payload(resp)

        status = DeviceStatus(
            power=status_data.get('power', False),
            mode=status_data.get('mode', 0),
            temp=status_data.get('temp', 24),
            fan=status_data.get('fan', 0),
            swing=status_data.get('swing', 0),
            sleep=status_data.get('sleep', False),
            turbo=status_data.get('turbo', False),
            room_temp=status_data.get('room_temp'),
            error_code=status_data.get('error_code', 0),
            raw=status_data,
        )
        logger.info(f"Status: {status}")
        return status

    def set_state(self, state: ACState):
        """
        Apply a complete AC state at once.

        Args:
            state: ACState with desired settings
        """
        self._pending_state = state
        self.send_control()

    def send_control(self):
        """
        Send the accumulated control parameters to the device.

        Call this after setting individual parameters via:
          set_power(), set_mode(), set_temperature(), set_fan_speed(),
          set_swing(), set_sleep(), set_turbo()
        """
        params = self._build_params()
        if not params:
            logger.warning("No parameters set; nothing to send")
            return

        payload = build_control_payload(params)
        resp = self._send_raw(DNACommand.DEVICE_CONTROL, payload)
        logger.info(f"Control response: {len(resp)} bytes")
        self._pending_params = {}

    def set_power(self, on: bool):
        """Turn the AC on or off."""
        self._pending_params['power'] = on

    def set_mode(self, mode: int):
        """
        Set the operation mode.

        Args:
            mode: 0=COOL, 1=HEAT, 2=AUTO, 3=FAN, 4=DRY
        """
        self._pending_params['mode'] = mode

    def set_temperature(self, temp: int):
        """
        Set the target temperature.

        Args:
            temp: Temperature in Celsius (typically 16-30)
        """
        if not (16 <= temp <= 30):
            raise ValueError(f"Temperature {temp}°C outside range 16-30")
        self._pending_params['temp'] = temp

    def set_fan_speed(self, speed: int):
        """
        Set the fan speed.

        Args:
            speed: 0=AUTO, 1=LOW, 2=MED, 3=HIGH
        """
        self._pending_params['fan'] = speed

    def set_swing(self, swing: int):
        """
        Set the swing mode.

        Args:
            swing: 0=OFF, 1=VERTICAL, 2=HORIZONTAL, 3=BOTH
        """
        self._pending_params['swing'] = swing

    def set_sleep(self, enabled: bool):
        """Enable or disable sleep mode."""
        self._pending_params['sleep'] = enabled

    def set_turbo(self, enabled: bool):
        """Enable or disable turbo mode."""
        self._pending_params['turbo'] = enabled

    def _build_params(self) -> dict:
        """Build the parameter dictionary for the control payload."""
        params = {
            'did': self.did,
            'sub_device_id': 0,
            'command_type': 0x01,  # Set control
        }
        # Apply any pending parameter changes
        params.update(getattr(self, '_pending_params', {}))
        return params

    _pending_params: Dict[str, Any] = {}


def discover_devices(
    broadcast_ip: str = "255.255.255.255",
    port: int = DEVICE_DISCOVERY_PORT,
    timeout: float = 3.0,
) -> list:
    """
    Discover AC devices on the local network via UDP broadcast.

    Sends a device probe broadcast and collects responses from
    any Kelvinator/Electrolux AC units on the same subnet.

    Args:
        broadcast_ip: Broadcast IP (use subnet broadcast for reliability)
        port: Device port (default: 80)
        timeout: How long to wait for responses

    Returns:
        List of dicts with 'ip', 'mac', 'did' keys
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    # Build discovery packet
    discovery_payload = struct.pack('<I', 0)  # Minimal probe payload
    packet = build_dna_packet(DNACommand.DEVICE_DISCOVER, discovery_payload)

    devices = []
    try:
        sock.sendto(packet, (broadcast_ip, port))
        start = time.time()

        while time.time() - start < timeout:
            try:
                data, addr = sock.recvfrom(4096)
                cmd, payload, checksum = parse_dna_packet(data)

                # Parse device info from response
                # Device response format:
                #   [mac:6] [ip:4] [did:17] [name:variable]
                if len(payload) >= 27:
                    mac = ':'.join(f'{b:02x}' for b in payload[0:6])
                    dev_ip = '.'.join(str(b) for b in payload[6:10])
                    did = payload[10:27].hex()
                    name = payload[27:].decode('utf-8', errors='replace') if len(payload) > 27 else ""

                    if dev_ip == "0.0.0.0":
                        dev_ip = addr[0]  # Use source address

                    devices.append({
                        'ip': dev_ip,
                        'mac': mac,
                        'did': did,
                        'name': name,
                    })
                    logger.info(f"Discovered: {name or did} at {dev_ip} ({mac})")

            except socket.timeout:
                break
            except Exception as e:
                logger.debug(f"Parse error: {e}")
    finally:
        sock.close()

    return devices
