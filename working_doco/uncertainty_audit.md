# Uncertainty Audit — Kelvinator-HASS-Addon

> Every assumption, unverified behavior, and ambiguous interpretation in the codebase.
> Format: UNC-{ID} {SEVERITY} — {CATEGORY} — {STATUS}

## Status Legend
- **RESOLVED**: Evidence collected, fix applied or assumption confirmed correct
- **REDUCED**: Evidence collected, uncertainty narrowed but not eliminated
- **OPEN**: No evidence available, needs investigation

---

### UNC-01 — BLOCKER — ASSUMPTION — REDUCED
**File**: `kelvinator_dna/protocol.py:39-49` (PARAM_* constants)

**Statement**: Param IDs 0x01-0x0B map to DevConstants.java string keys in a 1:1 linear fashion.
**Evidence**: Java SDK `e.java::a(BLStdControlParam)` serializes params as STRING names
(`"ac_pwr"`, `"ac_mode"`, `"ac_mark"`). The SO's `networkapi_dna_control` maps strings to
binary IDs internally. Our numeric IDs are a RE guess at the SO's internal mapping.
**Status**: REDUCED. We know the string names are correct (from DevConstants.java). We do
NOT know the wire-level binary IDs. Risk: if local UDP used, wrong binary IDs → commands
silently fail. Resolution still requires packet capture or Frida hooking.
**Code Marker**: `# UNC-01: Param IDs inferred from binary analysis; verify via packet capture`

---

### UNC-02 — HIGH — ASSUMPTION — REDUCED
**File**: `kelvinator_dna/protocol.py:88-92` (DID truncation)

**Statement**: 34-char cloud DIDs truncated to last 32 chars for wire protocol.
**Evidence**: Cloud API returns 34-char hex strings. Wire TFB format uses 16 bytes (32 chars).
**Status**: REDUCED. Truncation direction confirmed plausible but not verified. The extra 2
chars could be a prefix or checksum. Resolution: capture real device UDP packet and compare.
**Code Marker**: `# UNC-02: DID truncation assumed — verify with packet capture`

---

### UNC-03 — HIGH — ASSUMPTION — RESOLVED
**File**: `kelvinator_dna/protocol.py:0x05` (PARAM_SWING)

**Statement**: Single param ID 0x05 encodes swing as combined value.
**Evidence**: Java DeviceSwingActivity.java checks `ac_hdir` and `ac_vdir` independently.
The app sends two separate params. BLStdControlParam serialization confirms one param per entry.
**Status**: RESOLVED. Fix applied: climate.py removed horizontal swing (hdir param ID unknown).
PARAM_SWING=0x05 mapped to vertical only. Horizontal swing blocked until its param ID is discovered.
**Code Marker**: Removed from code. Comment added explaining two-param architecture.

---

### UNC-04 — MEDIUM — AMBIGUOUS — OPEN
**File**: `broadlink_api/crypto.py:85-98` (PKCS7 for device UDP)

**Statement**: Device-level encryption uses PKCS7 padding.
**Evidence For**: SO `bl_sdk_tfb_encode` uses PKCS7. This is called from `networkapi_dna_control`.
**Evidence Against**: python-broadlink uses zero-padding and works with real Broadlink devices.
**Status**: OPEN. Cannot resolve without packet capture or real device test.
**Code Marker**: `# UNC-04: PKCS7 for device UDP assumed from SO — verify vs live traffic`

---

### UNC-05 — MEDIUM — AMBIGUOUS — OPEN
**File**: `broadlink_api/protocol.py:0x20` (header checksum)

**Statement**: Header checksum is `sum(packet, 0xBEAF) & 0xFFFF`.
**Evidence**: Matches python-broadlink library. SO has Fletcher-16 variant with seeds (5,10).
**Status**: OPEN. Two different algorithms exist in different contexts. Cannot determine
which the device actually uses. python-broadlink algorithm is the safer default.
**Code Marker**: `# UNC-05: checksum algorithm matches python-broadlink; SO uses Fletcher-16 variant`

---

### UNC-06 — MEDIUM — INCOMPLETE_RE — RESOLVED
**File**: `kelvinator_dna/protocol.py:0x07` (PARAM_TURBO)

**Statement**: Param ID 0x07 is "turbo toggle", may be unused.
**Evidence**: DeviceFanActivity.java uses `ac_mark` (fan speed) for turbo — value 4 = turbo.
Turbo is validated against mode (only COOL and HEAT). No separate turbo param in app code.
**Status**: RESOLVED. PARAM_TURBO=0x07 is unused. Turbo is fan speed 4. Removed from
active code path; kept as constant for documentation.
**Code Marker**: Comment updated.

---

### UNC-07 — MEDIUM — ASSUMPTION — OPEN
**File**: `kelvinator_dna/protocol.py:167` (zero-padding sentinel)

**Statement**: `param_id=0x00 && param_len=0x00` marks end of param blocks.
**Status**: OPEN. Untestable without real device status response capture.
**Code Marker**: `# UNC-07: 0x00 sentinel assumed — verify with real status response`

---

### UNC-08 — LOW — ASSUMPTION — OPEN
**File**: `kelvinator_dna/protocol.py:19` (sub_device_id)
**Status**: OPEN. Unchanged. Untestable without multi-zone AC hardware.

---

### UNC-09 — LOW — ASSUMPTION — OPEN
**File**: `broadlink_api/protocol.py:14` (CMD_DEVICE_STATUS=0x6B)
**Status**: OPEN. Unchanged. Harmless dead code.

---

### UNC-10 — MEDIUM — ASSUMPTION — REDUCED
**File**: `api.py:112` (login ZeroBytePadding)

**Statement**: Cloud login uses ZeroBytePadding (NUL bytes).
**Evidence**: Java SDK `BLCommonTools.aesNoPadding()` confirmed via decompiled source.
**Status**: REDUCED. Java code confirms ZeroBytePadding. Login request not captured in HAR
to confirm server actually accepts it, but the Java code is authoritative. Fixed applied.
**Code Marker**: Already documented in function docstring.

---

### UNC-11 — HIGH — CONTRADICTORY — OPEN
**File**: `broadlink_api/crypto.py` vs `api.py`
**Statement**: Device UDP uses PKCS7; cloud login uses ZeroBytePadding. Two schemes.
**Status**: OPEN. Cannot determine which device UDP expects without packet capture.
**Code Marker**: `# UNC-11: device UDP PKCS7 vs cloud ZeroBytePadding; verify device expects`

---

### UNC-12 — MEDIUM — INCOMPLETE_RE — OPEN
**File**: `so_bridge.py:39-62` (JNI signatures)
**Status**: OPEN. SO never loads. Signatures are academic until SO becomes loadable.

---

### UNC-13 — LOW — ASSUMPTION — OPEN
**File**: `const.py:19` (COMPANY_ID)
**Status**: OPEN. Single APK version source. Extra APK versions would confirm constancy.

---

### UNC-14 — MEDIUM — ASSUMPTION — OPEN
**File**: `cloud.py:260` (family API padding)
**Status**: OPEN. HAR-verified but Java code not checked. Low risk since it works.

---

### UNC-15 — BLOCKER — MISSING_EVIDENCE — OPEN
**Statement**: Entire local UDP control path untested against real hardware.
**Resolution**: **Highest priority**. Test with physical Kelvinator AC. Capture all UDP traffic.
Without this, all local UDP assumptions (UNC-01, UNC-04, UNC-05, UNC-07) remain unverified.

---

## Resolution Summary

| UNC | Severity | Status | Action |
|-----|----------|--------|--------|
| 01  | BLOCKER  | REDUCED | String names confirmed, binary IDs unverified |
| 02  | HIGH     | REDUCED | Truncation plausible, unverified |
| **03** | **HIGH** | **RESOLVED** | Two-param swing confirmed; hdir blocked |
| 04  | MEDIUM   | OPEN | PKCS7 assumed, unverified |
| 05  | MEDIUM   | OPEN | Two checksum algorithms, unverified |
| **06** | **MEDIUM** | **RESOLVED** | Turbo = fan 4, no separate param |
| 07  | MEDIUM   | OPEN | Sentinel unverified |
| 08  | LOW      | OPEN | Multi-zone untested |
| 09  | LOW      | OPEN | Dead constant |
| 10  | MEDIUM   | REDUCED | Java code confirms ZeroBytePadding |
| 11  | HIGH     | OPEN | Two padding schemes, unverified |
| 12  | MEDIUM   | OPEN | SO never loads |
| 13  | LOW      | OPEN | Single APK source |
| 14  | MEDIUM   | OPEN | HAR-verified but not Java-verified |
| 15  | BLOCKER  | OPEN | Entire local UDP path untested |

**Resolved: 2** | **Reduced: 3** | **Open: 10**

### Required to close all remaining OPEN:
1. **Physical Kelvinator AC** + UDP packet capture (resolves UNC-01, 02, 04, 05, 07, 11, 15)
2. **Frida hook on Android emulator** (resolves UNC-01 binary IDs)
3. **Multi-zone AC hardware** (resolves UNC-08)
4. **Additional APK versions** (resolves UNC-13)
5. **Java decompilation of family API body encryption** (resolves UNC-14)
