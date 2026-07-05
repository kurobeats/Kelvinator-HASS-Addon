# Kelvinator DNA Protocol Documentation

Reverse-engineered from the Kelvinator/Electrolux Android APK (com.kelvinator.airconditioner).

## Architecture

```
Cloud API (HTTPS)                    Local UDP (DNA Protocol)
├── account/login ──── login ────┐  ├── Discovery (broadcast :80)
├── ec4/v1/common/api ── api key │  ├── Auth (CMD_AUTH 0x65)
├── user/getfamilyid ── family ──┤  ├── Control (CMD_DEVICE_CONTROL 0x6A)
└── family/getallinfo ── devices ┘  └── Status query (same 0x6A, TFB type=0x02)
         │                                    │
         ├── did, mac, aes_key, password ─────┘
         │
         └── (device IPs from LAN broadcast discovery)
```

## DNA Protocol (Broadlink 0x38-byte header)

Source: `../custom_components/kelvinator/broadlink_api/protocol.py`

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 8 | Magic: `5A A5 AA 55 5A A5 AA 55` |
| 0x08 | 4 | Reserved |
| 0x0C | 4 | Packet type |
| 0x10 | 2 | Length (LE) |
| 0x12 | 2 | Reserved |
| 0x14 | 4 | Reserved |
| 0x18 | 4 | Count |
| 0x1C | 4 | Unknown |
| 0x20 | 2 | Header checksum (sum of entire packet, seed 0xBEAF) |
| 0x22 | 2 | Error code (0 = success) |
| 0x24 | 2 | Device type (0x4F9B = 20379 for AC) |
| 0x26 | 2 | Command |
| 0x28 | 2 | Count |
| 0x2A | 6 | MAC address |
| 0x30 | 4 | Device ID (LE) |
| 0x34 | 2 | Payload checksum |
| 0x36 | 2 | Reserved |

## Encryption

- **Algorithm**: AES-128-CBC
- **Padding**: Zero-padding (NUL bytes to 16-byte boundary)
- **IV**: `562e17996d093d28ddb3ba695a2e6f58` (Broadlink standard)
- **Key**: Device AES key from cloud API (32-char hex = 16 bytes)
- **Checksum**: 2-byte LE sum prepended before encryption, seed 0xBEAF

After decryption, strip the first 2 bytes (checksum) and last NUL-padding bytes.

### Cloud API Encryption
- **Family API**: Same AES-128-CBC, zero-padding to `(len//16 + 2) * 16` bytes
- **IV**: `EA AA AA 3A BB 58 62 A2 19 18 B5 77 1D 16 15 AA`
- **Key**: Server key from `/ec4/v1/common/api` response

## TFB Payload Format (AC Commands)

Source: `../custom_components/kelvinator/kelvinator_dna/protocol.py`

```
[did:16 bytes]          — Device ID (32 hex chars = 16 bytes; cloud DIDs are 34 chars, use last 32)
[sub_device_id:2 LE]    — Sub-device index (0 for main unit)
[command_type:1]        — 0x01 = set control, 0x02 = query status
[param_id:1][len:1][val:N] — Repeated parameter blocks
```

### Known Parameter IDs

| ID | Name | Type | Values |
|----|------|------|--------|
| 0x01 | power | bool | 0=off, 1=on |
| 0x02 | mode | int | 0=cool, 1=heat, 2=dry, 3=fan, 4=auto, 5=eco, 6=eight_heat, 7=twelve_heat |
| 0x03 | temp | int | 16-30°C |
| 0x04 | fan | int | 0=auto, 1=low, 2=med, 3=high, 4=turbo, 5=quiet, 6=low_med, 7=med_high |
| 0x05 | swing | int | 0=off, 1=vert, 2=horiz, 3=both |
| 0x06 | sleep | bool | 0=off, 1=on |
| 0x07 | turbo | bool | (may be unused — turbo is a fan level) |
| 0x08 | temp_unit | int | 0=°C, 1=°F |
| 0x09 | room_temp | int | (read-only, from status response) |
| 0x0a | error_code | int | (read-only) |
| 0x0b | screen_display | bool | 0=display off, 1=display on |

**⚠️ UNTESTED**: These param IDs were inferred from binary analysis of `libNetworkAPI.so`. They have NOT been validated against live device traffic. See `ghidra_findings.md` for verification plan.

## Cloud API Endpoints

Source: `BLApiUrls.java` from decompiled APK

| Endpoint | Purpose |
|----------|---------|
| `{license}bizaccount.ibroadlink.com/account/login` | User authentication |
| `{license}bizihcv0.ibroadlink.com/ec4/v1/common/api` | Get API key + server timestamp |
| `{license}bizihcv0.ibroadlink.com/ec4/v1/user/getfamilyid` | Get family/home IDs |
| `{license}bizihcv0.ibroadlink.com/ec4/v1/family/getallinfo` | Get all devices with AES keys |
| `{license}thirdpartyservice.ibroadlink.com/thirdparty/v1/timetask/*` | Schedule management |

## libNetworkAPI.so JNI Exports

Source: `../custom_components/kelvinator/kelvinator_dna/so_bridge.py`

| JNI Export | Args | Purpose |
|------------|------|---------|
| `SDKInit` | (String configJson) | Initialize SDK |
| `dnaControl` | (String devInfo, String subDevInfo, String data, String cmdDesc) | Device control |
| `deviceStatusOnServer` | (String config, String did) | Cloud relay status |
| `deviceProbe` | (String did) | LAN device probe |
| `devicePair` | (String did, String config) | Device pairing |
| `deviceProfile` | (String did, String pid, String version) | Device profile |
| `LicenseInfo` | (String license) | License information |

## Known Limitations

1. **libNetworkAPI.so won't load on Linux/HA OS** — Android ARM binary, missing bionic libc/liblog.so
2. **Local UDP path not wired into HA** — `kelvinator_dna/device.py::KelvinatorDevice` exists but is only used by CLI
3. **TFB param IDs unverified** — need live device packet capture or Frida hooking
4. **HAR capture incomplete** — login request and device control not captured

## Next Steps (RE)

1. Capture real app's UDP traffic with tcpdump/Wireshark between phone and AC unit
2. Compare wire-format payloads to `build_control_payload()` output
3. Frida-hook `NetworkAPI.dnaControl()` on Android emulator for exact argument values
4. If param IDs confirmed, wire `KelvinatorDevice` (local UDP) into HA coordinator
