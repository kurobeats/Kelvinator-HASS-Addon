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
  [did:16]                    - Device ID (16 bytes; HAR-verified from cloud API)
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
# Verified against HAR cloud API: devtype=20379, pid contains 0x4F9B at offset 12-14 (LE)
AC_DEVTYPE = 0x4F9B  # 20379

# --- Control Payload Parameter IDs ---
# UNC-01: These IDs (0x01-0x0B) are inferred from libNetworkAPI.so binary
# analysis.  They have NOT been validated against live device traffic.
# Verify via Frida hook or UDP packet capture before relying on local UDP.
# UNC-06: PARAM_TURBO=0x07 semantics unclear — may be unused (turbo is fan=4)
PARAM_POWER = 0x01       # ac_pwr: power (0/1)
PARAM_MODE = 0x02        # ac_mode: 0=cool, 1=heat, 2=dry, 3=fan, 4=auto
PARAM_TEMP = 0x03        # ac_temp: target temp (°C)
PARAM_FAN = 0x04         # ac_mark: fan speed (0=auto, 1=low, 2=med, 3=high, 4=turbo, 5=quiet, 6=low_med, 7=med_high)
PARAM_SWING = 0x05       # UNC-03: ac_vdir: vertical swing (0=off, 1=on).
# Horizontal swing (ac_hdir) param ID unknown — may be 0x0C or separate.
# The app sends ac_vdir and ac_hdir as two independent string params.
# Until verified, only vertical swing is supported via PARAM_SWING.
PARAM_SLEEP = 0x06       # ac_slp: sleep (0/1)
PARAM_TURBO = 0x07       # (dedicated turbo toggle; may be unused — turbo is a fan level)
PARAM_TEMP_UNIT = 0x08   # temperature unit (0=°C, 1=°F)
PARAM_ROOM_TEMP = 0x09   # room temperature (read-only, from status response)
PARAM_ERROR_CODE = 0x0a  # error code (read-only)
PARAM_SCREEN = 0x0b       # scrdisp: screen/display brightness (0=off, 1=on)

PARAM_NAMES = {
    PARAM_POWER: 'power',
    PARAM_MODE: 'mode',
    PARAM_TEMP: 'temp',
    PARAM_FAN: 'fan',
    PARAM_SWING: 'swing',
    # UNC-06: PARAM_TURBO=0x07 likely unused — turbo is ac_mark=4
    # Verified: DeviceFanActivity.java sends "ac_mark" with value 4 for turbo.
    PARAM_SLEEP: 'sleep',
    PARAM_TURBO: 'turbo',
    PARAM_TEMP_UNIT: 'temp_unit',
    PARAM_ROOM_TEMP: 'room_temp',
    PARAM_ERROR_CODE: 'error_code',
    PARAM_SCREEN: 'screen_display',
}


# --- TFB Control Payload Builder ---

def build_control_payload(params: Dict[str, Any]) -> bytes:
    """
    Build a TFB control/status payload for the Kelvinator AC.

    This is the unencrypted payload that will be AES-CBC encrypted by
    broadlink_api and sent with the 0x38-byte Broadlink DNA header.

    Payload structure:
        [did:16]                           - Device ID (16 bytes from 32-char hex string)
        [sub_device_id:2 LE]               - Sub-device ID (default 0)
        [command_type:1]                   - 0x01=set control, 0x02=query status
        [param_id:1][param_len:1][value:N] - Repeated parameter blocks

    Args:
        params: Dict with keys:
            did: str — Device ID hex string (32 chars = 16 bytes; HAR-verified)
            sub_device_id: int — Sub-device index (0 for main unit)
            command_type: int — 1=set control, 2=query status
            power: bool
            mode: int (0=cool, 1=heat, 2=dry, 3=fan, 4=auto)
            temp: int (Celsius, 16-30)
            fan: int (0=auto, 1=low, 2=med, 3=high, 4=turbo, 5=quiet, 6=low_med, 7=med_high)
            swing: int (0=off, 1=vert, 2=horiz, 3=both)
            sleep: bool
            turbo: bool
            screen_display: bool
            temp_unit: int (0=Celsius, 1=Fahrenheit)
    """
    payload = bytearray()

    # UNC-02: Cloud API returns 34-char DIDs.  We truncate to last 32 chars
    # (16 bytes).  Verify with packet capture that this is the correct
    # transformation.
    did_hex = params.get('did', '')
    if len(did_hex) > 32:
        did_hex = did_hex[-32:]
    did = bytes.fromhex(did_hex)
    if len(did) != 16:
        raise ValueError(f"DID must be 16 bytes (32 hex chars), got {len(did)} from {params.get('did', '')}")
    payload.extend(did)

    # Sub-device ID (2 bytes LE)
    payload.extend(struct.pack('<H', params.get('sub_device_id', 0)))

    # Command type
    payload.append(params.get('command_type', 0x01))

    # Parameter blocks
    # UNC-01: Param IDs below inferred from binary analysis.  The Java SDK
    # sends STRING param names ("ac_pwr", "ac_mode", etc.) — the SO maps
    # them to wire-level IDs internally.  These binary IDs are our best
    # guess at the SO's internal mapping.  Verify via packet capture.
    _append_param(payload, PARAM_POWER, params.get('power'))
    _append_param(payload, PARAM_MODE, params.get('mode'))
    _append_param(payload, PARAM_TEMP, params.get('temp'))
    _append_param(payload, PARAM_FAN, params.get('fan'))
    _append_param(payload, PARAM_SWING, params.get('swing'))
    _append_param(payload, PARAM_SLEEP, params.get('sleep'))
    _append_param(payload, PARAM_TURBO, params.get('turbo'))
    _append_param(payload, PARAM_TEMP_UNIT, params.get('temp_unit'))
    _append_param(payload, PARAM_SCREEN, params.get('screen_display'))

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
        [did:16]                                 - Device ID (16 bytes)
        [sub_device_id:2 LE]                     - Sub-device ID
        [param_id:1][param_len:1][value:variable] - Parameter blocks, repeated

    Returns:
        Dict with keys: power, mode, temp, fan, swing, sleep, turbo,
        screen_display, room_temp, error_code, etc. Plus 'did' and 'sub_device_id'.
    """
    if len(data) < 18:
        raise ValueError(f"Status payload too short: {len(data)} bytes")

    result: Dict[str, Any] = {}
    pos = 0

    # DID: 16 bytes (32 hex chars; HAR-verified)
    result['did'] = data[pos:pos + 16].hex()
    pos += 16

    # Sub-device ID
    if pos + 2 <= len(data):
        result['sub_device_id'] = struct.unpack('<H', data[pos:pos + 2])[0]
        pos += 2

    # Parse parameter blocks
    while pos + 2 <= len(data):
        param_id = data[pos]
        param_len = data[pos + 1]
        # UNC-07: Assumes 0x00 0x00 sentinel marks end of param list.
        # Verify with real device status response.
        if param_id == 0x00 and param_len == 0x00:
            break
        pos += 2

        if pos + param_len > len(data):
            break

        value = data[pos:pos + param_len]
        pos += param_len

        name = PARAM_NAMES.get(param_id, f'param_0x{param_id:02x}')

        if param_id in (PARAM_POWER, PARAM_SLEEP, PARAM_TURBO, PARAM_SCREEN):
            result[name] = value[0] != 0
        elif param_id in (PARAM_MODE, PARAM_TEMP, PARAM_FAN, PARAM_SWING,
                          PARAM_TEMP_UNIT, PARAM_ROOM_TEMP, PARAM_ERROR_CODE):
            result[name] = value[0]
        else:
            result[name] = value

    return result
