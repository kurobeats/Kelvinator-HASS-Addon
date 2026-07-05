# DNA Protocol Packet Map

> Complete reference for the BroadLink DNA protocol used by Kelvinator/Electrolux AC units.
> Sources: decompiled APK (Android), libNetworkAPI.so objdump disassembly,
> python-broadlink library, HAR captures.

## Overview

The BroadLink DNA protocol operates over **UDP** (default port 80) with a fixed
**0x38-byte header** followed by an **AES-128-CBC encrypted payload**.

For cloud relay, packets are wrapped in an **0x54-byte cloud header** and sent
over HTTPS to `bizihcv0.ibroadlink.com` family API endpoints.

---

## 1. DNA Device Packet (UDP)

### Header Layout (0x38 = 56 bytes)

```
Offset  Size  Name              Value / Notes
------  ----  ----              --------------
0x00    8     Magic             5A A5 AA 55 5A A5 AA 55
0x08    4     Reserved          00 00 00 00
0x0C    4     Reserved          00 00 00 00
0x10    2     Length           Payload length (LE)
0x12    2     Reserved          00 00
0x14    4     Reserved          00 00 00 00
0x18    4     Count             01 00 00 00
0x1C    4     Unknown           00 00 00 00
0x20    2     Header checksum   sum(packet_bytes, 0xBEAF) & 0xFFFF
0x22    2     Error code      0 = success, negative = error (e.g. -6)
0x24    2     Device type     LE (0x4F9B = 20379 for Kelvinator AC)
0x26    2     Command         LE (see Command IDs below)
0x28    2     Count           LE, bit 15 always set
0x2A    6     MAC address     Reversed byte order
0x30    4     Device ID       LE
0x34    2     Payload checksum sum(payload, 0xBEAF) & 0xFFFF
0x36    2     Padding          00 00
```

### Command IDs

| Value  | Name              | Purpose |
|--------|-------------------|---------|
| 0x03   | CMD_LOGIN         | Login |
| 0x06   | CMD_DEVICE_INFO   | Device info query |
| 0x65   | CMD_AUTH          | Authentication handshake |
| 0x6A   | CMD_DEVICE_CONTROL | Device control + status query |
| 0x6B   | CMD_DEVICE_STATUS  | Status query (unused — all via 0x6A) |

### Command Byte Details

- **0x65 (AUTH)**: Handshake to obtain device_id and session key.
  Payload: 0x50 bytes with magic at +0x04:0x14 (0x31 × 16)

- **0x6A (DEVICE_CONTROL)**: All device operations. The TFB `command_type` byte
  inside the payload distinguishes SET (0x01) from QUERY (0x02).

### Checksum Algorithm

```python
def header_checksum(packet: bytes) -> int:
    """Sum entire packet (header + encrypted payload), seed 0xBEAF."""
    return (sum(packet, 0xBEAF)) & 0xFFFF

def payload_checksum(payload: bytes) -> int:
    """Sum plaintext payload, seed 0xBEAF."""
    return (sum(payload, 0xBEAF)) & 0xFFFF
```

**SO variant** (from `bl_sdk_getsum` disassembly — may be for cloud path only):
```c
// Fletcher-16 with seeds (5, 10)
uint32_t bl_sdk_getsum(uint8_t *data, int len) {
    uint16_t sum1 = 5, sum2 = 10;
    for (int i = 0; i < len; i++) {
        sum1 = (sum1 + data[i]) & 0xFFFF;
        sum2 = (sum2 + sum1) & 0xFFFF;
    }
    return (sum2 << 16) | sum1;
}
```

### Encryption

| Parameter | Value |
|-----------|-------|
| Algorithm | AES-128-CBC |
| IV (device) | `562e17996d093d28ddb3ba695a2e6f58` (BroadLink standard) |
| IV (cloud API) | `EA AA AA 3A BB 58 62 A2 19 18 B5 77 1D 16 15 AA` (OEM-specific) |
| Padding | PKCS7 (pad byte = pad count; verified via SO disassembly of `bl_sdk_tfb_encode`) |
| Key source | Cloud API → `/family/getallinfo` → `aeskey` field (32 hex chars = 16 bytes) |
| Auth key | BroadLink default: `09 76 28 34 3F E9 9E 23 76 5C 15 13 AC CF 8B 02` |

### Encryption Pipeline

```
Plaintext payload
  → PKCS7 pad to 16-byte boundary
  → AES-128-CBC encrypt (device key, BroadLink IV)
  → Prepend 0x38-byte header
  → Compute header checksum over entire packet
  → Send via UDP to device:80
```

### Decryption Pipeline

```
Receive UDP packet
  → Validate header checksum
  → Check error code at 0x22 (non-zero = rejection)
  → Extract encrypted payload at offset 0x38
  → AES-128-CBC decrypt (device key, BroadLink IV)
  → Strip PKCS7 padding (verify pad bytes)
  → Return plaintext payload
```

---

## 2. TFB Payload Format (AC Commands)

The decrypted payload for `CMD_DEVICE_CONTROL` (0x6A) contains a TFB block:

```
[did:16 bytes]         Device ID (32 hex chars, or last 32 of 34-char cloud DID)
[sub_device_id:2 LE]   Sub-device index (0x0000 for main unit)
[command_type:1]       0x01 = SET control, 0x02 = QUERY status
[param_id:1][len:1][val:len] ...  Repeated parameter blocks
[PKCS7 padding]        Padding fills to 16-byte boundary
```

### Parameter ID Table

| ID   | DevConstants Key    | Type   | Values |
|------|---------------------|--------|--------|
| 0x01 | `ac_pwr`            | bool   | 0=off, 1=on |
| 0x02 | `ac_mode`           | u8     | 0=cool, 1=heat, 2=dry, 3=fan, 4=auto, 5=eco, 6=8°C-heat, 7=12°C-heat |
| 0x03 | `temp`              | u8     | 16-30 (°C) |
| 0x04 | `ac_mark`           | u8     | 0=auto, 1=low, 2=med, 3=high, 4=turbo, 5=quiet, 6=low-med, 7=med-high |
| 0x05 | `ac_vdir`           | u8/bool| 0=off, 1=vert-on |
| 0x06 | `ac_slp`            | bool   | 0=off, 1=on |
| 0x07 | `turbo`             | bool   | Turbo toggle (may be unused — turbo is fan=4) |
| 0x08 | `tempunit`          | u8     | 0=°C, 1=°F |
| 0x09 | `envtemp`           | u8     | Room temperature (read-only) |
| 0x0A | `ac_errcode`        | u8     | Error code (read-only) |
| 0x0B | `scrdisp`           | bool   | Display on/off |

> ⚠️ **Status**: IDs 0x01-0x0B inferred from binary analysis. NOT validated against live device traffic.
> See `tests/ghidra_findings.md` for Frida-based verification plan.

### Unmapped Parameters (from DevConstants.java)

These devices support 30+ additional parameters. Their wire-level IDs are unknown:

| DevConstants Key       | Description |
|------------------------|-------------|
| `ac_hdir`              | Horizontal swing |
| `timer`                | Timer setting |
| `ac_timingtime`        | Schedule timing |
| `ac_timingenable`      | Schedule enable |
| `modelnumber`          | Model number |
| `sn`                   | Serial number |
| `ecomode`              | Eco mode toggle |
| `qtmode`               | Quiet mode |
| `ac_clean`             | Self-clean |
| `mldprf`               | Mould-proof |
| `anionmode`            | Ionizer |
| `drmode`               | Demand response |
| `espmode`              | ESP mode |
| `disimode`             | Disinfection |
| `filreset`             | Filter reset |
| `smarteyes`            | Smart eye sensor |
| `insectrepellent`      | Mosquito repellent |
| `coldplasma`           | Cold plasma |
| `ac_compressorstatus`  | Compressor status (RO) |
| `ac_fourwayvalvestatus`| 4-way valve (RO) |
| `ac_heaterstatus`      | Heater (RO) |
| `ac_indoorfanstatus`   | Indoor fan (RO) |
| `ac_evapordefroststate`| Defrost state (RO) |

---

## 3. Discovery Packet (UDP Broadcast)

Sent to `255.255.255.255:80` for device discovery.

```
Offset  Size  Field
------  ----  -----
0x00    4     Reserved (00 00 00 00)
0x04    4     Reserved (00 00 00 00)
0x08    2     Year (LE)
0x0A    1     Seconds
0x0B    1     Minutes
0x0C    1     Hours
0x0D    1     Weekday (1=Sun)
0x0E    1     Day
0x0F    1     Month
0x10    4     Reserved (00 00 00 00)
0x14    4     Reserved (00 00 00 00)
0x18    4     Source IP (reversed bytes)
0x1C    2     Source port (LE)
0x1E    2     Reserved (00 00)
0x20    2     Checksum
0x22    2     Reserved (00 00)
0x24    2     Reserved (00 00)
0x26    1     Flag (0x06 = discover)
0x27    9     Reserved (00...)
```
Total: 0x30 bytes.

### Response Format

```
Offset  Size  Field
------  ----  -----
0x34    2     Device type (LE)
0x3A:6  6     MAC (reversed)
0x40+   var   Device name (NUL-terminated UTF-8)
0x7F    1     is_locked flag
```
Total varies, typically 0x80+ bytes.

---

## 4. Cloud Data Packet (HTTPS Relay)

When relayed through BroadLink cloud servers, device packets use an 0x54-byte
cloud header wrapping the encrypted payload.

### Cloud Header (`bl_sdk_cloud_data_pack`)

```
Offset  Size  Field
------  ----  -----
0x00    0x14  Cloud header (format TBD — see Ghidra analysis)
0x14    0x02  device_info+0x50 (endian-swapped if flag set)
0x16    0x02  device_info+0x52
0x18    0x04  device_info+0x70 (endian-swapped if flag set)
0x1C    0x24  Reserved
0x40    0x14  Encrypted payload area start
0x54    var   Encrypted TFB payload
```

### Device Info Struct Fields

| Offset | Size | Purpose |
|--------|------|---------|
| +0x50  | 2    | Device type or command code |
| +0x52  | 2    | Sub-command or sequence |
| +0x70  | 4    | Device ID or timestamp |

---

## 5. Example Packets

### Example 1: SET power=ON, mode=COOL, temp=22°C

```
TFB Payload (plaintext, 23 bytes):
  DID:    00000000000000000000a1b2c3d4e5f6  (16 bytes)
  SUB:    0000                              (2 bytes LE)
  CMD:    01                                (SET)
  PWR:    01 01 01                          (param=0x01, len=1, val=1)
  MODE:   02 01 00                          (param=0x02, len=1, val=0=cool)
  TEMP:   03 01 16                          (param=0x03, len=1, val=22)

After PKCS7 padding (to 32 bytes): ... + 09 09 09 09 09 09 09 09 09
After AES-CBC encrypt: [32 bytes ciphertext]
DNA Header: [0x38 bytes]
Total packet: [0x38 + 32 = 0x58 bytes]
```

### Example 2: QUERY device status

```
TFB Payload (plaintext):
  DID:    00000000000000000000a1b2c3d4e5f6  (16 bytes)
  SUB:    0000                              (2 bytes LE)
  CMD:    02                                (QUERY)

After PKCS7 padding (to 32 bytes): ... + 0D 0D 0D 0D 0D 0D 0D 0D 0D 0D 0D 0D 0D
After AES-CBC encrypt: [32 bytes]
DNA Header with command=0x6A
Total: 0x58 bytes
```

### Example 3: Auth Handshake

```
Payload (0x50 bytes):
  00: 00 00 00 00 31 31 31 31 31 31 31 31 31 31 31 31
  10: 31 31 31 31 00 00 00 00 00 00 00 00 00 00 01 00
  20: 00 00 00 00 00 00 00 00 00 00 00 00 01 54 65 73
  30: 74 20 31 00 00 00 00 00 00 00 00 00 00 00 00 00
  40: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00

DNA Header: command=0x65, devtype=0x4F9B, key=default

Response (decrypted):
  device_id: 4 bytes LE at offset 0
  session_key: 16 bytes at offset 4
```

---

## 6. Ghidra MCP Analysis Targets

### Verified from SO disassembly
- [x] `bl_sdk_tfb_encode` uses PKCS7 padding (pad byte = pad count)
- [x] `bl_sdk_tfb_decode` validates PKCS7 padding on decrypt
- [x] AES-128 key (0x80 bits) passed to `broadlink_tfb_setkey_enc`
- [x] Encryption via `broadlink_tfb_crypt_fef(mode=1/0, ...)`
- [x] `bl_sdk_getsum` = Fletcher-16 variant (seeds 5,10)
- [x] Cloud packets have 0x54-byte header minimum
- [x] Device info struct at +0x50, +0x52, +0x70

### Not yet verified from SO
- [ ] Param ID dispatch logic in `networkapi_dna_control` (0xdd600, 3837 bytes)
- [ ] Exact mapping of param IDs 0x01-0x0B to DevConstants.java keys
- [ ] Param IDs for 30+ undocumented DevConstants keys
- [ ] `ac_hdir` (horizontal swing) param ID
- [ ] Cloud header 0x00:0x14 field format
- [ ] `bl_sdk_auth` 13-parameter TLS/ECDH internal flow

### Frida verification plan (recommended)
```javascript
Java.perform(function() {
    var NA = Java.use("cn.com.broadlink.networkapi.NetworkAPI");
    NA.dnaControl.implementation = function(a,b,c,d) {
        console.log("dnaControl(" + a + ", " + b + ", " + c + ", " + d + ")");
        return this.dnaControl(a,b,c,d);
    };
});
```

---

## 7. Unresolved Questions

1. **Param ID 0x07 (turbo)** — unused in practice? Turbo is fan speed 4.
   Does the device have a separate turbo toggle?

2. **Horizontal swing** — `ac_hdir` is in DevConstants.java but no known
   param ID. Does the device use a combined swing param (0x05 with 2/3)
   or separate vdir/hdir?

3. **`CMD_DEVICE_STATUS = 0x6B`** — defined but never used. All status
   queries go through CMD_DEVICE_CONTROL (0x6A) with TFB command_type=0x02.
   Is 0x6B a legacy command or model-specific?

4. **Checksum divergence** — The SO uses Fletcher-16 (5,10), but python-broadlink
   uses simple sum with 0xBEAF seed. Both work with devices? Or are they used
   for different contexts (device UDP vs cloud relay)?

5. **DID length** — Cloud API returns 34-char DIDs. Wire protocol uses 16 bytes
   (32 hex chars). Are the first 2 chars a prefix or is the full 17-byte DID
   truncated from the right?

6. **Cloud relay viability** — Can the cloud relay work without the full SDK
   auth (bl_sdk_auth)? The Python workspace uses direct family API calls.
   Is the cloud relay path (`deviceStatusOnServer`) accessible without SDK auth?

7. **Firmware version fragmentation** — Different Kelvinator models may have
   different param ID mappings or feature sets. The decompiled APK is one
   snapshot. Are there known firmware variants?

---

## 8. Integration Checklist

- [x] Mode constants match ACCommonUtils.java
- [x] Fan constants match DevConstants.java
- [x] PKCS7 padding in crypto.py (was zero-padding — fixed)
- [x] DID tolerance for 34→32 char in protocol.py (fixed)
- [ ] Wire-level param IDs verified via Frida or packet capture
- [ ] Horizontal swing param ID resolved
- [ ] Cloud relay path tested (or documented as unsupported)
- [ ] Model-specific feature flags documented
