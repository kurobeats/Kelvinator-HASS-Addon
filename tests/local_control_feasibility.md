# Local-Only Control Feasibility Analysis

> Can the Kelvinator HA integration control AC units without cloud authentication?

## Architecture Overview

```
                    ┌──────────────────────┐
                    │   Cloud (BroadLink)   │
                    │                       │
                    │  /account/login       │  → userid, loginsession
                    │  /ec4/v1/common/api   │  → API key
                    │  /family/getallinfo   │  → did, mac, aes_key, password, pid, name
                    └──────┬───────────────┘
                           │
                    ┌──────▼───────────────┐
                    │   HA Integration      │
                    │                       │
                    │  KelvinatorCoordinator│
                    │  KelvinatorACDevice   │
                    └──────┬───────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
    ┌─────────▼──────┐       ┌─────────▼──────┐
    │  Cloud Relay   │       │   Local UDP    │
    │  (DEAD PATH)   │       │  (NEEDS WIRING)│
    │                │       │                │
    │ DNACloudRelay  │       │ KelvinatorDevice│
    │   → so_bridge  │       │  → BroadlinkDev│
    │   → SO (fails) │       │  → UDP :80     │
    │   → no-op      │       │  → AES-CBC     │
    └────────────────┘       │  → TFB payload │
                             └────────────────┘
```

## Local Control Code Paths (already exist)

### 1. DNS Transport Layer — `broadlink_api/`
**Status**: Complete. 4 files, 693 LOC.

| Module | Purpose |
|--------|---------|
| `broadlink_api/device.py` | `BroadlinkDevice` — UDP auth + command send |
| `broadlink_api/protocol.py` | 0x38-byte DNA header builder/parser |
| `broadlink_api/crypto.py` | AES-128-CBC with PKCS7 padding |
| `broadlink_api/__init__.py` | Package exports |

**What it does correctly**:
- UDP send/receive on port 80 ✓
- 0x38-byte Broadlink DNA header with magic, devtype, MAC, device_id ✓
- Header checksum over full packet ✓
- AES-128-CBC encrypt/decrypt with Broadlink IV ✓
- Device authentication (CMD_AUTH handshake → get device_id → update_key) ✓
- LAN device discovery (UDP broadcast to 255.255.255.255:80) ✓
- Error code checking at 0x22 before decryption ✓

### 2. AC-Specific TFB Layer — `kelvinator_dna/device.py`
**Status**: Complete but untested.

| Module | Purpose |
|--------|---------|
| `kelvinator_dna/device.py` | `KelvinatorDevice` — AC device with TFB payloads |
| `kelvinator_dna/protocol.py` | TFB payload builder/parser |
| `kelvinator_dna/commands.py` | `ACState`, `ACMode`, `FanSpeed`, `SwingMode` |

**What it does**:
- Wraps `BroadlinkDevice` with AC-specific logic ✓
- `build_control_payload()` — TFB payload builder ✓
- `parse_status_payload()` — TFB response parser ✓
- `get_status()` — Query device state ✓
- `set_state()` — Send control commands ✓
- Individual control methods (set_power, set_mode, set_temp, etc.) ✓

## Cloud Dependencies

### What Cloud Provides (bootstrap only)

| Credential | Source | Used For |
|-----------|--------|----------|
| `aes_key` | `/family/getallinfo` response | AES-128-CBC encryption key for UDP |
| `password` | `/family/getallinfo` response | Device authentication (4-byte XOR) |
| `did` | `/family/getallinfo` response | Device identifier in TFB payload |
| `mac` | `/family/getallinfo` response | Device MAC for DNA header |
| `pid` | `/family/getallinfo` response | Product ID |
| `devtype` | Hardcoded (0x4F9B) | Device type in DNA header |

### What Cloud Does NOT Provide (needed for local control)

| Need | How to Get |
|------|-----------|
| Device IP address | LAN broadcast discovery (`BroadlinkDevice.discover()`) |
| Device reachability | UDP probe after IP discovery |

### What Cloud IS Necessary For

1. **Device credential bootstrap**: AES key and password are only available from cloud.
   Without cloud login, you cannot get these credentials.
2. **Remote access**: When not on the same LAN, cloud relay is the only path.

### What Cloud is NOT Necessary For

1. **Device control**: Once you have AES key + password + IP, all control is local UDP.
2. **Device status**: Same — local UDP query.
3. **Device discovery on LAN**: UDP broadcast, no cloud needed.

## Feasibility Matrix

| Capability | Cloud Required? | Local Only? | Notes |
|-----------|----------------|-------------|-------|
| Initial setup / pairing | YES | NO | AES key only from cloud API |
| Credential caching | — | YES | Store AES key/ password locally after first cloud fetch |
| Device control | NO | YES | Local UDP with cached credentials |
| Device status | NO | YES | Local UDP |
| LAN discovery | NO | YES | UDP broadcast |
| Remote access (WAN) | YES | NO | Cloud relay required |
| Firmware update | YES | NO | Cloud API |
| Schedule management | YES | NO | Cloud API (`/thirdparty/v1/timetask/*`) |

**Key insight**: Cloud is required ONCE for credential bootstrap. After that, all local
operations work without cloud. This is how the official Electrolux app works.

## Implementation Plan

### Phase 1: Wire Local UDP Into HA (HIGH EFFORT, HIGH REWARD)

```
KelvinatorCoordinator._async_setup():
  1. Cloud login → get devices + credentials
  2. LAN broadcast discovery → get IPs
  3. Match MACs → create KelvinatorDevice per device
  4. Authenticate + update_key per device
  5. Store KelvinatorDevice in self.devices

KelvinatorCoordinator._async_update_data():
  1. For each KelvinatorDevice: await dev.get_status()
  2. Map DeviceStatus → AcDeviceState

KelvinatorACDevice.send_command():
  1. Delegate to KelvinatorDevice.set_state()
```

**Files to change**:
- `api.py`: Remove `DNACloudRelay`/`DNALocalRelay`. Add `KelvinatorDevice` to `KelvinatorACDevice`.
- `coordinator.py`: Add LAN discovery. Wire `KelvinatorDevice` per device.
- `climate.py`: No changes (already uses `KelvinatorACDevice.send_command()`).

**Risks**:
- UNC-01: Param IDs unverified against real device
- UNC-04: PKCS7 padding assumed for device UDP
- UNC-15: Entire local UDP path untested against real hardware
- DID format may differ between cloud and local UDP
- Device auth may fail with different firmware versions

### Phase 2: Credential Caching (MEDIUM EFFORT)

Store device credentials (aes_key, password, did, mac) in HA's config entry or storage.
On restart, attempt local control first. Only hit cloud if:
- Credentials are missing (first run)
- All devices are unreachable (credentials may have changed)

### Phase 3: Remove Dead Cloud Relay Code (LOW EFFORT)

Delete once local UDP is confirmed working:
- `libNetworkAPI.so` (1.25MB)
- `so_bridge.py` (204 LOC)
- `DNACloudRelay` / `DNALocalRelay` classes
- SO path detection code at top of `api.py`

## Risks and Blockers

### BLOCKER: No Physical Hardware Test

The entire local UDP path has never been tested against a real Kelvinator AC unit.
All assumptions about packet format, param IDs, encryption, and device behavior
are unverified. Without a test, Phase 1 is purely speculative.

### HIGH: Cloud Credential Bootstrap Still Required

Even with local control, you MUST log in to the cloud at least once to get the
AES key. There is no known way to extract the AES key from the device directly.
The key is provisioned during manufacturing and stored in BroadLink's cloud.

### MEDIUM: Credential Rotation

If BroadLink rotates device credentials, cached credentials become invalid.
Need cloud re-login to refresh. Frequency unknown.

### LOW: Firmware Updates

Local control may break after device firmware updates. Need cloud login to
check for new firmware and re-discover devices.

## What's Blocking Phase 1

The single biggest blocker is **UNC-15: no physical hardware test**. Everything
else is engineering. The path is clear:

1. Get physical Kelvinator AC on same LAN
2. Cloud login → get credentials
3. LAN discovery → get IP
4. `KelvinatorDevice.connect()` → auth → `get_status()`
5. If step 4 works → wire into HA coordinator
6. If step 4 fails → capture UDP traffic, debug, retry

No amount of RE or Ghidra analysis can substitute for a 5-minute test with real hardware.
