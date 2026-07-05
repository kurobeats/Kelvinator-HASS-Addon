# Cloud Relay Protocol Analysis

> From `libNetworkAPI.so` binary analysis via objdump disassembly.

## Architecture

The cloud relay path uses two separate mechanisms:
1. **Local DNA protocol**: UDP to device (covered by `broadlink_api/`)
2. **Cloud relay**: HTTP POST to BroadLink servers which forward to device

The cloud relay is implemented in:
- `bl_sdk_cloud_data_pack` at 0xc4ec0 — Build cloud relay packets
- `bl_sdk_cloud_data_unpack` at 0xc5470 — Parse cloud relay responses
- `networkapi_device_status_on_server` at 0xcf740 — Full cloud status query
- `networkapi_dna_control` at 0xdd600 — Cloud control command

## Cloud Data Packet Structure (`bl_sdk_cloud_data_pack`)

```
Signature: bl_sdk_cloud_data_pack(uint8_t *dst, int dst_len,
                                   uint8_t *data_src, int data_len,
                                   void *device_info)
```

### Packet Layout

```
Offset  Size  Field
------  ----  -----
0x00    0x14  Cloud header (20 bytes, format TBD)
0x14    0x02  Field from device_info+0x50 (byteswapped if endian flag set)
0x16    0x02  Field from device_info+0x52 (byteswapped if endian flag set)
0x18    0x04  Field from device_info+0x70 (byteswapped if endian flag set)
0x1C    0x24  Reserved/zero
0x40    var   Encrypted payload (AES-CBC, TFB-encoded)
```

### Device Info Struct

The `device_info` parameter is a struct with fields at known offsets:
- `+0x50`: 2 bytes — possibly device type or command code
- `+0x52`: 2 bytes — possibly sub-command or sequence number
- `+0x70`: 4 bytes — possibly device ID or timestamp

Values are byte-swapped (big-endian → little-endian) based on an endianness flag
checked via a function at 0xc5e50.

### Function Flow

1. Check: `dst_len >= data_len + 0x54` (minimum packet size = payload + 84-byte header)
2. Copy payload data to `dst + 0x14 + 0x40` (= `dst + 0x54`)
3. Write device_info fields with optional byteswap
4. Total packet = 0x54 + data_len bytes

## Cloud Status Query (`networkapi_device_status_on_server`)

Located at 0xcf740, this function:
- Stack frame: 0x1500 bytes (5376) — large buffer for cloud JSON payloads
- Uses **BLJSON** (cJSON fork) for all JSON operations
- Two code paths based on `global_var->b1` flag (byte at offset 0xb1)

### Path 1: Flag != 2 — Parse cloud response
```
BLJSON_Parse(input_json)
  → Extract specific fields
  → Build response JSON with {status, msg, data}
```

### Path 2: Flag == 2 — Send to cloud
```
Build JSON with BLJSON_CreateObject/BLJSON_AddItemToObject
  → Serialize
  → POST to cloud endpoint
  → Parse response
```

### Cloud Response Format

The cloud relay returns JSON with standard structure:
```json
{
  "status": 0,       // 0=success, negative=error
  "msg": "...",      // Human-readable message
  "data": {          // Device state (only on success)
    "ac_pwr": 1,
    "ac_mode": 0,
    "temp": 24,
    ...
  }
}
```

### JSON Operations Used

| BLJSON Function | PLT Address | Purpose |
|---|---|---|
| `BLJSON_CreateObject` | 0x1b1b0 | Create JSON object `{}` |
| `BLJSON_Parse` | 0x1b1c0 | Parse JSON string |
| `BLJSON_AddItemToObject` | 0x18a10 | Add key-value pair |
| `BLJSON_CreateString` | 0x18a70 | Create JSON string value |
| `BLJSON_CreateNumber` | 0x18a60 | Create JSON number value |
| `BLJSON_InitHooks` | 0x1eb40 | Initialize JSON memory hooks |

## Cloud API Endpoints (from decompiled Java)

Family API base: `https://{license}bizihcv0.ibroadlink.com`

| Endpoint | Purpose | Used by |
|---|---|---|
| `/ec4/v1/common/api` | Get API key + timestamp | `KelvinatorCloud.authenticate()` |
| `/ec4/v1/user/getfamilyid` | Get family/home IDs | `KelvinatorCloud.get_family_id()` |
| `/ec4/v1/family/getallinfo` | Get devices + AES keys | `KelvinatorCloud.discover_devices()` |

Account API: `https://{license}bizaccount.ibroadlink.com`

| Endpoint | Purpose | Used by |
|---|---|---|
| `/account/login` | User authentication | `api.py::_cloud_login_sync()` |

## How Cloud Relay Differs from Local UDP

| Aspect | Local UDP | Cloud Relay |
|---|---|---|
| Transport | UDP port 80 | HTTPS (TLS) |
| Header | 0x38-byte DNA header | 0x54-byte cloud header |
| Encryption | AES-128-CBC (device key) | AES-128-CBC (server key) |
| Auth | CMD_AUTH handshake | Login session token |
| Payload | TFB (raw binary) | TFB inside JSON envelope |
| Latency | < 100ms | 500-2000ms |
| Requires | LAN access | Internet access |

## Existing Workspace Impacts

### ✅ Correct
- `cloud.py::KelvinatorCloud` family API flow matches decompiled app
- `api.py::_cloud_login_sync` account/login flow matches observed behavior
- Device info parsing from `/family/getallinfo` response

### ⚠️ Issues
1. **SSL disabled**: `cloud.py::_make_request()` used `ssl.CERT_NONE` (fixed in this review cycle)
2. **API_HOST hardcoded**: Was hardcoded to Kelvinator license; now dynamic (fixed)
3. **No cloud relay fallback**: Cloud relay via `libNetworkAPI.so` can never work on Linux.
   The `DNALocalRelay` no-op leaves devices in stale state. The integration needs local
   UDP control as the primary path, with cloud relay as a documented fallback.

### 📋 Recommended Changes
1. Wire `kelvinator_dna/device.py::KelvinatorDevice` (local UDP) as primary control path
2. Cloud API remains for: credential bootstrap (login → get AES keys)
3. Cloud relay is NOT needed if local UDP works — delete `DNACloudRelay`/`DNALocalRelay`
4. Document that cloud relay is only useful for remote access (outside LAN)

## Packet Capture Verification

The HAR file (`tests/output.har`) captures the cloud discovery flow:
- ✅ `/ec4/v1/common/api` — get API key
- ✅ `/ec4/v1/user/getfamilyid` — get family ID
- ✅ `/ec4/v1/family/getallinfo` — get devices

The HAR does NOT capture:
- ❌ Login request (`/account/login`) — happened before proxy start
- ❌ Cloud relay commands — those go through `libNetworkAPI.so`, not standard HTTP
- ❌ Local UDP traffic — out of scope for mitmproxy

To verify cloud relay packet format, capture raw UDP traffic between the Android app
and a physical AC unit, OR capture the app's HTTP traffic to `bizihcv0.ibroadlink.com`
during a device control operation.
