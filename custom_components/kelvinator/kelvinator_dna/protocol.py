"""
DNA Protocol: Low-level packet encoding, encryption, and TFB serialization.

The BroadLink DNA (Device Network API) protocol stack:
  Layer 1: UDP Transport
  Layer 2: DNA Packet Framing (header + payload)
  Layer 3: AES-128-ECB Encryption (per-device key)
  Layer 4: TFB (Type-Field-Body) Serialization

Packet Format (DNA):
  [0x5a, 0xa5]  - Magic header (2 bytes)
  [length]       - Payload length, little-endian uint16 (2 bytes)
  [cmd_hi]       - Command high byte
  [cmd_lo]       - Command low byte
  [payload]      - Variable length (encrypted TFB or plain)

TFB Format:
  [type]  - 1 byte type identifier
  [field] - Variable-length field data
  [body]  - Variable-length body data

Encryption:
  AES-128-ECB with PKCS#7 padding.
  Key is the per-device 16-byte AES key (retrieved from cloud API).
  The first 16 bytes of the TFB payload are XOR'd with a checksum derived
  from the device password before encryption.

Checksum:
  A 16-bit checksum computed over the payload (before encryption).
  Stored at the end of the DNA packet.
"""

import struct
import hashlib
from typing import Tuple, Optional
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


# --- DNA Packet Constants ---
DNA_MAGIC = b'\x5a\xa5'
DNA_HEADER_SIZE = 6  # magic(2) + length(2) + cmd(2)
DNA_CHECKSUM_SIZE = 2
DNA_MAX_PAYLOAD = 1024


# --- Known Command IDs ---
class DNACommand:
    """DNA protocol command IDs."""
    DEVICE_DISCOVER = 0x0001      # Device discovery / probe
    DEVICE_INFO = 0x0002          # Device information query
    DEVICE_CONTROL = 0x006a       # Main device control command
    DEVICE_STATUS = 0x006b        # Device status query
    DEVICE_SUB_CONTROL = 0x006c   # Sub-device control
    DEVICE_PAIR = 0x0003          # Device pairing
    DEVICE_BIND = 0x0004          # Device binding
    FIRMWARE_UPDATE = 0x000e      # Firmware update
    HEARTBEAT = 0x0000            # Keep-alive / heartbeat
    AUTH_REQUEST = 0x0065         # Authentication request
    AUTH_RESPONSE = 0x0066        # Authentication response


# --- TFB Type Constants ---
TFB_TYPE_STRING = 0x00
TFB_TYPE_INT = 0x01
TFB_TYPE_BOOL = 0x02
TFB_TYPE_BYTES = 0x03
TFB_TYPE_ARRAY = 0x04
TFB_TYPE_MAP = 0x05
TFB_TYPE_FLOAT = 0x06


# --- Packet Assembly ---

def build_dna_packet(command: int, payload: bytes) -> bytes:
    """
    Build a DNA protocol packet.

    Structure:
        [magic:2] [length:2 LE] [cmd:2 BE] [payload:N] [checksum:2 BE]

    Args:
        command: 16-bit command ID
        payload: Encrypted or plain payload bytes

    Returns:
        Complete DNA packet bytes
    """
    cmd_hi = (command >> 8) & 0xFF
    cmd_lo = command & 0xFF
    pkt_len = len(payload) + 2  # payload + checksum

    # Calculate checksum over the payload
    checksum = _compute_checksum(payload)

    packet = bytearray()
    packet.extend(DNA_MAGIC)                      # [0:2] magic
    packet.extend(struct.pack('<H', pkt_len))      # [2:4] length (LE)
    packet.append(cmd_hi)                          # [4] cmd hi
    packet.append(cmd_lo)                          # [5] cmd lo
    packet.extend(payload)                         # [6:N+6] payload
    packet.extend(struct.pack('>H', checksum))     # [N+6:N+8] checksum (BE)

    return bytes(packet)


def parse_dna_packet(data: bytes) -> Tuple[int, bytes, int]:
    """
    Parse a DNA protocol packet.

    Returns:
        Tuple of (command_id, payload, checksum)
    """
    if len(data) < DNA_HEADER_SIZE + DNA_CHECKSUM_SIZE:
        raise ValueError(f"Packet too short: {len(data)} bytes")

    if data[0:2] != DNA_MAGIC:
        raise ValueError(f"Invalid magic: {data[0:2].hex()}")

    pkt_len = struct.unpack('<H', data[2:4])[0]
    command = (data[4] << 8) | data[5]
    payload = data[6:6 + pkt_len - 2]
    checksum = struct.unpack('>H', data[6 + pkt_len - 2:6 + pkt_len])[0]

    return command, payload, checksum


def _compute_checksum(data: bytes) -> int:
    """
    Compute the DNA 16-bit checksum.

    Based on the bl_checksum / bl_tfb_checksum functions in libNetworkAPI.so.
    This is a simple sum of all bytes modulo 65536.
    """
    return sum(data) & 0xFFFF


# --- AES Encryption ---

class DNAEncryption:
    """
    AES-128-ECB encryption/decryption for DNA protocol payloads.

    Uses the per-device AES key retrieved from the BroadLink cloud API.
    Before encryption, the first 16 bytes are XOR'd with a key derived
    from the device password (a 32-bit integer).
    """

    BLOCK_SIZE = 16  # AES-128 block size

    def __init__(self, aes_key: bytes):
        """
        Args:
            aes_key: 16-byte AES-128 key (hex decoded from cloud API)
        """
        if len(aes_key) != 16:
            raise ValueError(f"AES key must be 16 bytes, got {len(aes_key)}")
        self.key = aes_key

    def encrypt(self, plaintext: bytes, device_password: int = 0) -> bytes:
        """
        Encrypt a TFB payload for sending to the device.

        Args:
            plaintext: TFB-encoded payload bytes
            device_password: Device password from cloud API (4-byte int)

        Returns:
            AES-ECB encrypted bytes
        """
        # If device_password is non-zero, derive a XOR key from it
        if device_password:
            xor_key = _derive_xor_key(device_password)
            # XOR the key with the first 16 bytes (or less) of plaintext
            plaintext = bytearray(plaintext)
            for i in range(min(len(plaintext), 16)):
                plaintext[i] ^= xor_key[i % len(xor_key)]
            plaintext = bytes(plaintext)

        # Pad to 16-byte boundary (PKCS#7)
        padded = pad(plaintext, self.BLOCK_SIZE)

        # AES-128-ECB encrypt
        cipher = AES.new(self.key, AES.MODE_ECB)
        return cipher.encrypt(padded)

    def decrypt(self, ciphertext: bytes, device_password: int = 0) -> bytes:
        """
        Decrypt a TFB payload received from the device.

        Args:
            ciphertext: AES-ECB encrypted bytes
            device_password: Device password from cloud API (4-byte int)

        Returns:
            Decrypted TFB payload bytes
        """
        cipher = AES.new(self.key, AES.MODE_ECB)
        padded = cipher.decrypt(ciphertext)

        # Remove PKCS#7 padding
        plaintext = unpad(padded, self.BLOCK_SIZE)

        # If device_password is non-zero, XOR back
        if device_password:
            xor_key = _derive_xor_key(device_password)
            plaintext = bytearray(plaintext)
            for i in range(min(len(plaintext), 16)):
                plaintext[i] ^= xor_key[i % len(xor_key)]
            plaintext = bytes(plaintext)

        return plaintext


def _derive_xor_key(password: int) -> bytes:
    """
    Derive an XOR key from the device password.

    The password is a 32-bit integer. The key is derived by
    taking the password bytes and extending to 16 bytes.
    """
    pw_bytes = struct.pack('>I', password)
    # Repeat the 4-byte password to fill 16 bytes
    return (pw_bytes * 4)[:16]


# --- TFB Serialization ---

class TFBEncoder:
    """
    Serialize Python data structures to TFB (Type-Field-Body) format.

    TFB is a binary serialization format used by BroadLink's protocol.
    It's similar to a simplified version of BSON or MessagePack.
    """

    @staticmethod
    def encode_string(value: str) -> bytes:
        """Encode a string field."""
        data = value.encode('utf-8')
        return struct.pack('<H', len(data)) + data

    @staticmethod
    def encode_int(value: int) -> bytes:
        """Encode a 32-bit integer field."""
        return struct.pack('<I', value)

    @staticmethod
    def encode_short(value: int) -> bytes:
        """Encode a 16-bit integer field."""
        return struct.pack('<H', value)

    @staticmethod
    def encode_byte(value: int) -> bytes:
        """Encode a single byte field."""
        return struct.pack('B', value)

    @staticmethod
    def encode_bytes(value: bytes) -> bytes:
        """Encode a raw bytes field."""
        return struct.pack('<H', len(value)) + value

    @staticmethod
    def encode_bool(value: bool) -> bytes:
        """Encode a boolean field."""
        return b'\x01' if value else b'\x00'

    @staticmethod
    def encode_array(items: list, item_encoder) -> bytes:
        """Encode an array of items."""
        result = struct.pack('<H', len(items))
        for item in items:
            result += item_encoder(item)
        return result


class TFBDecoder:
    """
    Deserialize TFB (Type-Field-Body) format data.
    """

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read_bytes(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise IndexError(f"Not enough data: need {n}, have {self.remaining()}")
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def read_byte(self) -> int:
        return self.read_bytes(1)[0]

    def read_short(self) -> int:
        return struct.unpack('<H', self.read_bytes(2))[0]

    def read_int(self) -> int:
        return struct.unpack('<I', self.read_bytes(4))[0]

    def read_bool(self) -> bool:
        return self.read_byte() != 0

    def read_string(self) -> str:
        length = self.read_short()
        return self.read_bytes(length).decode('utf-8')

    def read_bytes_field(self) -> bytes:
        length = self.read_short()
        return self.read_bytes(length)


# --- Device Control Payload Builder ---

def build_control_payload(params: dict) -> bytes:
    """
    Build a device control TFB payload from a parameter dictionary.

    The DNA control command uses a specific binary format for AC control.
    Based on analysis of the protocol and the NetworkAPI.dnaControl() JNI call,
    the payload is structured as a TFB message containing:

      - Device ID (DID): 17 bytes
      - Sub-device ID: 2 bytes (0x0000 for main device)
      - Command type: 1 byte
      - Parameter blocks: variable

    Args:
        params: Dictionary of control parameters
            - 'did': Device ID string (hex)
            - 'power': bool - Power on/off
            - 'mode': int - Operation mode (0=cool, 1=heat, 2=auto, 3=fan, 4=dry)
            - 'temp': int - Target temperature (16-30 °C)
            - 'fan': int - Fan speed (0=auto, 1=low, 2=med, 3=high)
            - 'swing': int - Swing mode (0=off, 1=vertical, 2=horizontal, 3=both)
            - 'sleep': bool - Sleep mode
            - 'turbo': bool - Turbo mode

    Returns:
        TFB-encoded control payload bytes
    """
    payload = bytearray()

    # Device ID (hex string → binary, variable length: 16-17 bytes)
    did = bytes.fromhex(params.get('did', ''))
    if len(did) not in (16, 17):
        raise ValueError(f"DID must be 16-17 bytes, got {len(did)}")
    payload.extend(did)

    # Sub-device ID (2 bytes, default 0)
    payload.extend(struct.pack('<H', params.get('sub_device_id', 0)))

    # Command type byte
    payload.append(params.get('command_type', 0x01))

    # --- Parameter blocks ---
    # Each parameter: [param_id:1] [length:1] [value:variable]

    # Power
    if 'power' in params:
        payload.append(0x01)  # Param ID: Power
        payload.append(0x01)  # Length
        payload.append(0x01 if params['power'] else 0x00)

    # Mode
    if 'mode' in params:
        payload.append(0x02)  # Param ID: Mode
        payload.append(0x01)
        payload.append(params['mode'] & 0xFF)

    # Temperature
    if 'temp' in params:
        payload.append(0x03)  # Param ID: Temperature
        payload.append(0x01)
        payload.append(params['temp'] & 0xFF)

    # Fan speed
    if 'fan' in params:
        payload.append(0x04)  # Param ID: Fan
        payload.append(0x01)
        payload.append(params['fan'] & 0xFF)

    # Swing
    if 'swing' in params:
        payload.append(0x05)  # Param ID: Swing
        payload.append(0x01)
        payload.append(params['swing'] & 0xFF)

    # Sleep
    if 'sleep' in params:
        payload.append(0x06)  # Param ID: Sleep
        payload.append(0x01)
        payload.append(0x01 if params['sleep'] else 0x00)

    # Turbo
    if 'turbo' in params:
        payload.append(0x07)  # Param ID: Turbo
        payload.append(0x01)
        payload.append(0x01 if params['turbo'] else 0x00)

    # Temperature unit (0=Celsius, 1=Fahrenheit)
    if 'temp_unit' in params:
        payload.append(0x08)
        payload.append(0x01)
        payload.append(params['temp_unit'] & 0xFF)

    return bytes(payload)


def parse_status_payload(data: bytes) -> dict:
    """
    Parse a device status response payload.

    Returns:
        Dictionary with device status information
    """
    if len(data) < 17:
        raise ValueError(f"Status payload too short: {len(data)}")

    result = {}
    pos = 0

    # DID (16-17 bytes)
    did_len = min(17, len(data) - pos)
    result['did'] = data[pos:pos+did_len].hex()
    pos += did_len

    # Sub-device ID (2 bytes)
    if pos + 2 <= len(data):
        result['sub_device_id'] = struct.unpack('<H', data[pos:pos+2])[0]
        pos += 2

    # Parse parameter blocks
    while pos + 2 <= len(data):
        param_id = data[pos]
        param_len = data[pos + 1]
        pos += 2

        if pos + param_len > len(data):
            break

        value = data[pos:pos + param_len]
        pos += param_len

        if param_id == 0x01:  # Power
            result['power'] = value[0] != 0
        elif param_id == 0x02:  # Mode
            result['mode'] = value[0]
        elif param_id == 0x03:  # Temperature
            result['temp'] = value[0]
        elif param_id == 0x04:  # Fan
            result['fan'] = value[0]
        elif param_id == 0x05:  # Swing
            result['swing'] = value[0]
        elif param_id == 0x06:  # Sleep
            result['sleep'] = value[0] != 0
        elif param_id == 0x07:  # Turbo
            result['turbo'] = value[0] != 0
        elif param_id == 0x09:  # Room temperature
            if param_len >= 1:
                result['room_temp'] = value[0]
        elif param_id == 0x0a:  # Error code
            if param_len >= 1:
                result['error_code'] = value[0]

    return result
