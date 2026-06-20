"""
Kelvinator AC Protocol: TFB (Type-Field-Body) payload serialization.

This module handles the Kelvinator/Electrolux AC-specific command
payload format that rides on top of the standard Broadlink DNA protocol
(0x38-byte header, AES-128-CBC) provided by `broadlink_api`.

The `broadlink_api` package handles all transport (UDP), encryption
(AES-CBC + checksum), and device discovery. This module only deals with
the AC-specific TFB payload format sent as the plaintext body of
CMD_DEVICE_CONTROL (0x6A) and CMD_DEVICE_STATUS (0x6B) packets.

TFB Payload Format (after Broadlink decryption):
  [did:17]                    - Device ID (raw bytes, 17 bytes)
  [sub_device_id:2 LE]        - Sub-device ID (0x0000 for main unit)
  [command_type:1]            - 0x01=set, 0x02=query status
  [param_id:1][param_len:1][value:variable]  - Repeated parameter blocks
"""

import struct
from typing import Dict, Any


# --- Command IDs ---
CMD_DEVICE_CONTROL = 0x6A   # Send control command
CMD_DEVICE_STATUS = 0x6B    # Query device status
CMD_AUTH = 0x65             # Authentication handshake

# --- Device type for Kelvinator/Electrolux AC ---
AC_DEVTYPE = 0x4F9B  # 20379

# --- Control Payload Parameter IDs ---
PARAM_POWER = 0x01
PARAM_MODE = 0x02
PARAM_TEMP = 0x03
PARAM_FAN = 0x04
PARAM_SWING = 0x05
PARAM_SLEEP = 0x06
PARAM_TURBO = 0x07
PARAM_TEMP_UNIT = 0x08
PARAM_ROOM_TEMP = 0x09
PARAM_ERROR_CODE = 0x0a

PARAM_NAMES = {
    PARAM_POWER: 'power',
    PARAM_MODE: 'mode',
    PARAM_TEMP: 'temp',
    PARAM_FAN: 'fan',
    PARAM_SWING: 'swing',
    PARAM_SLEEP: 'sleep',
    PARAM_TURBO: 'turbo',
    PARAM_TEMP_UNIT: 'temp_unit',
    PARAM_ROOM_TEMP: 'room_temp',
    PARAM_ERROR_CODE: 'error_code',
}


# --- TFB Control Payload Builder ---

def build_control_payload(params: Dict[str, Any]) -> bytes:
    """
    Build a TFB control/status payload for the Kelvinator AC.

    This is the unencrypted payload that will be AES-CBC encrypted by
    broadlink_api and sent with the 0x38-byte Broadlink DNA header.

    Payload structure:
        [did:N]                            - Device ID (16 or 17 bytes from hex)
        [sub_device_id:2 LE]               - Sub-device ID (default 0)
        [command_type:1]                   - 0x01=set control, 0x02=query status
        [param_id:1][param_len:1][value:N] - Repeated parameter blocks

    Args:
        params: Dict with keys:
            did: str — Device ID hex string (32-34 chars = 16-17 bytes)
            sub_device_id: int — Sub-device index (0 for main unit)
            command_type: int — 1=set control, 2=query status
            power: bool
            mode: int (0=cool, 1=heat, 2=auto, 3=fan, 4=dry)
            temp: int (Celsius, 16-30)
            fan: int (0=auto, 1=low, 2=med, 3=high)
            swing: int (0=off, 1=vert, 2=horiz, 3=both)
            sleep: bool
            turbo: bool
            temp_unit: int (0=Celsius, 1=Fahrenheit)
    """
    payload = bytearray()

    # Device ID (hex → bytes)
    did = bytes.fromhex(params.get('did', ''))
    if len(did) not in (16, 17):
        raise ValueError(f"DID must be 16-17 bytes, got {len(did)}")
    payload.extend(did)

    # Sub-device ID (2 bytes LE)
    payload.extend(struct.pack('<H', params.get('sub_device_id', 0)))

    # Command type
    payload.append(params.get('command_type', 0x01))

    # Parameter blocks
    _append_param(payload, PARAM_POWER, params.get('power'))
    _append_param(payload, PARAM_MODE, params.get('mode'))
    _append_param(payload, PARAM_TEMP, params.get('temp'))
    _append_param(payload, PARAM_FAN, params.get('fan'))
    _append_param(payload, PARAM_SWING, params.get('swing'))
    _append_param(payload, PARAM_SLEEP, params.get('sleep'))
    _append_param(payload, PARAM_TURBO, params.get('turbo'))
    _append_param(payload, PARAM_TEMP_UNIT, params.get('temp_unit'))

    return bytes(payload)


def _append_param(payload: bytearray, param_id: int, value) -> None:
    """Append a parameter block [id:1][len:1][val:N] if value is not None."""
    if value is None:
        return

    if isinstance(value, bool):
        value = 0x01 if value else 0x00
    elif isinstance(value, int):
        value = value & 0xFF
    else:
        raise TypeError(f"Unsupported param value type: {type(value)}")

    payload.append(param_id)
    payload.append(0x01)   # Length (always 1 for these params)
    payload.append(value)


# --- TFB Status Payload Parser ---

def parse_status_payload(data: bytes) -> Dict[str, Any]:
    """
    Parse a TFB status response payload from the AC device.

    Response structure:
        [did:16-17]                              - Device ID
        [sub_device_id:2 LE]                     - Sub-device ID
        [param_id:1][param_len:1][value:variable] - Parameter blocks, repeated

    Returns:
        Dict with keys: power, mode, temp, fan, swing, sleep, turbo,
        room_temp, error_code, etc. Plus 'did' and 'sub_device_id'.
    """
    if len(data) < 17:
        raise ValueError(f"Status payload too short: {len(data)} bytes")

    result: Dict[str, Any] = {}
    pos = 0

    # DID (try 17 bytes first, fall back to 16)
    did_len = 17 if len(data) >= 20 else 16
    result['did'] = data[pos:pos + did_len].hex()
    pos += did_len

    # Sub-device ID
    if pos + 2 <= len(data):
        result['sub_device_id'] = struct.unpack('<H', data[pos:pos + 2])[0]
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

        name = PARAM_NAMES.get(param_id, f'param_0x{param_id:02x}')

        if param_id in (PARAM_POWER, PARAM_SLEEP, PARAM_TURBO):
            result[name] = value[0] != 0
        elif param_id in (PARAM_MODE, PARAM_TEMP, PARAM_FAN, PARAM_SWING,
                          PARAM_TEMP_UNIT, PARAM_ROOM_TEMP, PARAM_ERROR_CODE):
            result[name] = value[0]
        else:
            result[name] = value

    return result
