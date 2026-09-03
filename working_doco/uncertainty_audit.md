# Uncertainty Audit — Kelvinator-HASS-Addon

> Every assumption, unverified behavior, and ambiguous interpretation in the codebase.
> Format: UNC-{ID} {SEVERITY} — {CATEGORY} — {STATUS}
>
> Updated 2026-09-03 after: decryption of the DNA Kit Lua script
> (`9b4f0000000000000000000000000000.script`), live output of the bundled
> `libNetworkAPI.so` on Linux, and packet-capture analysis.

## Status Legend
- **RESOLVED**: Evidence collected, fix applied or assumption confirmed correct
- **REDUCED**: Evidence collected, uncertainty narrowed but not eliminated
- **OBSOLETE**: The assumption became moot (protocol/format replaced)
- **OPEN**: No evidence available, needs investigation

---

### UNC-01 — BLOCKER — ASSUMPTION — OBSOLETE
**Statement**: Param IDs 0x01-0x0B map to DevConstants.java keys as binary IDs.
**Resolution**: There ARE no binary param IDs. The real payload embeds DNA Kit
*string* parameter names inside a JSON body. The TFB param-ID table was a wrong
guess; protocol.py rewritten to the real format. RESOLVED by decrypted DNA Kit
script (g_func table = complete list of 40 param names).

### UNC-02 — HIGH — ASSUMPTION — REDUCED
**Statement**: 34-char cloud DIDs truncated to last 32 chars for wire protocol.
**Resolution**: The JSON body carries the DID as a *string*; the SDK uses the
full DID from the sub-device info. Truncation is no longer relevant to the
payload layer. REDUCED (outer DNA header still uses a 4-byte device_id, which
the discovery response provides at offset 0x30).

### UNC-03 — HIGH — ASSUMPTION — RESOLVED
**Statement**: Single param ID 0x05 encodes swing.
**Resolution**: Swing is two independent string params: `ac_vdir` and `ac_hdir`
(both present in the DNA Kit script). Horizontal swing support is now possible;
not yet exposed in HA (kept vertical-only until tested).

### UNC-04 — MEDIUM — AMBIGUOUS — RESOLVED
**Statement**: Device UDP padding: PKCS7 vs zero-padding.
**Resolution**: PKCS7 confirmed for the SDK's packet encoder (`bl_sdk_tfb_encode`
Ghidra analysis); SDK also accepts zero-padding. Payload checksum sits INSIDE
the encrypted body at offsets 4-5 (seed 0xBEAF) — verified byte-exact against
live SDK output.

### UNC-05 — MEDIUM — ASSUMPTION — RESOLVED
**Statement**: Header checksum algorithm.
**Resolution**: Both exist in the SDK and are used in different contexts:
`bl_getcsum` = sum(bytes, 0xBEAF) (device payload path — verified against live
packets), `bl_sdk_getsum` = Fletcher-16 with seeds (5, 10) (cloud relay path).

### UNC-06 — MEDIUM — INCOMPLETE_RE — RESOLVED
Turbo: no dedicated param. Fan (`ac_mark`) value 4 = turbo. Confirmed by DNA
Kit script (`ac_mark` in [1,0,1,2,3,4,5,6,7]).

### UNC-07 — MEDIUM — ASSUMPTION — RESOLVED
**Statement**: 0x00 0x00 sentinel marks end of param blocks.
**Resolution**: Obsolete — there are no param blocks. The payload is
`[a5a55a5a][ck][cmd][0x0b][len:2][ver:2][JSON body]`; the JSON length field
is authoritative. RESOLVED via live SDK output.

### UNC-08 — LOW — ASSUMPTION — OPEN
Sub-device handling. Untested (no multi-zone hardware).

### UNC-09 — LOW — ASSUMPTION — RESOLVED
CMD_DEVICE_STATUS=0x6B never used — confirmed: all traffic rides CMD 0x6A
locally; the SDK's control path is a *cloud relay* (`{prefix}access.ibroadlink.com:1998`).

### UNC-10 — MEDIUM — ASSUMPTION — RESOLVED
Cloud login padding: PKCS7 works against the live server (verified; see git
history aa2cc77). ZeroBytePadding also accepted by the server.

### UNC-11 — HIGH — CONTRADICTORY — RESOLVED
Two padding schemes: both real, both accepted. Device path PKCS7 (per SDK
encoder), cloud login PKCS7 (works). No conflict in practice.

### UNC-12 — MEDIUM — INCOMPLETE_RE — RESOLVED
`libNetworkAPI.so` JNI signatures: the SO is an **x86-64 Linux/Android-NDK
build** and RUNS on Linux with a small shim (fake JNIEnv + bionic symbol
stubs). The whole DNA SDK (init, SDKAuth, dnaControl) is now drivable — see
`dna_sdk/dna_bridge.py`.

### UNC-13 — LOW — ASSUMPTION — OPEN
COMPANY_ID constancy across APK versions. Unchanged.

### UNC-14 — MEDIUM — ASSUMPTION — RESOLVED
Family API body encryption/padding: HAR-verified and works. Closed.

### UNC-15 — BLOCKER — MISSING_EVIDENCE — RESOLVED
**Statement**: Entire local UDP control path untested against real hardware.
**Resolution**: Tested. Result: **raw local UDP control is impossible** for
these devices — the official-app-style auth handshake is rejected with
errno -7 ("control key is expired") because the devices only accept
cloud-issued session keys (SDKAuth ECDH). Verified by live capture: the same
packets the app sends (default-key 0x65 auth, device_id 0) get -7. The SDK's
own control path is a cloud relay (`{prefix}access.ibroadlink.com:1998`).

## New uncertainties (2026-09-03)

### NUNC-01 — HIGH — OPEN
Exact SDKAuth parameter semantics (13 args). The JNI wrapper builds a
fixed-offset string blob; we replicate it, but the auth has not yet completed
end-to-end against the live cloud (blocked on valid account credentials —
login returns -1008 with the test account password).

### NUNC-02 — MEDIUM — OPEN
Cloud relay wire format on TCP :1998 (0x54-byte cloud header, bl_sdk_cloud_data_pack).
Not yet implemented in pure Python; the SDK handles it internally. Only needed
if replacing the SDK bridge with pure Python.

### NUNC-03 — MEDIUM — OPEN
Relay host shard prefix (`%uaccess.ibroadlink.com`). Prefix appears to derive
from the SDK session (auth state); "0" is used when unauthenticated. Exact
derivation unknown.

### NUNC-04 — LOW — OPEN
DNA Kit script delivery: the SDK expects `<pid>000000000000000000000000.script`
(24 zeros); the APK asset is named `<24 zeros><pid>`. SDK also supports
downloading scripts from the cloud (`resources_token`/appmanager endpoints).
We ship the APK asset renamed.

## Resolution Summary

| UNC | Severity | Status |
|-----|----------|--------|
| 01  | BLOCKER  | RESOLVED (protocol rewritten) |
| 02  | HIGH     | REDUCED |
| 03  | HIGH     | RESOLVED (ac_vdir + ac_hdir) |
| 04  | MEDIUM   | RESOLVED (PKCS7) |
| 05  | MEDIUM   | RESOLVED (sum 0xBEAF device / Fletcher cloud) |
| 06  | MEDIUM   | RESOLVED |
| 07  | MEDIUM   | RESOLVED (JSON body) |
| 08  | LOW      | OPEN |
| 09  | LOW      | RESOLVED |
| 10  | MEDIUM   | RESOLVED |
| 11  | HIGH     | RESOLVED |
| 12  | MEDIUM   | RESOLVED (SO runs on Linux via shim) |
| 13  | LOW      | OPEN |
| 14  | MEDIUM   | RESOLVED |
| 15  | BLOCKER  | RESOLVED (local UDP requires cloud session key) |

**Resolved: 12** | **Reduced: 1** | **Open: 2 (+4 new)**

### Remaining blockers
1. **Valid account credentials** to complete SDKAuth end-to-end (NUNC-01).
2. aarch64 build of the DNA SDK for ARM hosts (bundle the APK's arm64-v8a SO
   with the same shim technique).