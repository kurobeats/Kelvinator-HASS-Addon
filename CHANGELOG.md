# Changelog

## 2.1.0 (2026-09-03)

### Fixed
- **Wire protocol rewritten to ground truth.** The earlier TFB payload format
  (`[did:16][sub:2][cmd:1][param blocks]`) was a wrong RE guess. Real format
  (from the decrypted DNA Kit Lua script + live SDK output):
  `[a5a55a5a][ck:2 seed 0xBEAF][0x01 get/0x02 set][0x0b][len:2][ver:2][JSON]`
  with DNA Kit *string* parameter names (`ac_pwr`, `ac_mode`, `temp`, …).
  Resolves UNC-01 (no binary param IDs exist), UNC-07.
- **Checksums resolved** (UNC-05): device-path checksum is `sum(bytes, 0xBEAF)`
  (python-broadlink compatible). The SO's Fletcher-16 (seeds 5,10) variant is
  used only on the cloud relay path.
- **Padding resolved** (UNC-04/UNC-11): device-path uses PKCS7; the SDK also
  accepts zero-padding. Cloud login uses PKCS7 (deliberate, verified).
- Removed duplicate `AES.new` line in `_cloud_login_sync`.
- Manifest: `iot_class` corrected to `cloud_polling`; dropped unused `broadlink` requirement.

### Changed
- **Vendor SDK control path.** Device control/status now goes through the
  bundled official DNA SDK (`libNetworkAPI.so`, x86-64 Linux build) driven by
  a small subprocess bridge (`dna_sdk/dna_bridge.py`), including the SDKAuth
  (TLS+ECDH) cloud session registration these locked devices require.
- Coordinator no longer re-fetches the cloud device list on every poll.
- Deleted the dead `libNetworkAPI.so` cloud-relay stub code
  (`DNACloudRelay`/`DNALocalRelay`/`so_bridge.py`) that never worked.

### Known issues
- Local UDP control without the SDK: devices reject raw auth (0x65) with
  errno -7 ("control key is expired") — they require the cloud-issued
  control key from SDKAuth. Verified against live devices.
- SDK binary is x86-64 only.

## 2.0.0 (2026-06-17)

- Complete rewrite with bundled `kelvinator_dna` library (no unpublished pip dependencies)
- Cloud-first architecture: login and device discovery via BroadLink cloud API
- Local UDP control (did not work — DNA devices require cloud-issued control keys)
- Fixed Family API device discovery (AES-encrypted JSON body, correct token formula)
- Single-step config flow (username/password only)

## 1.0.0 (2026-06-14)

- Initial release
- BroadLink DNA protocol integration via python-broadlink
- MQTT auto-discovery for Home Assistant