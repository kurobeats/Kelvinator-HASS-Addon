# Kelvinator DNA Protocol Documentation

Reverse-engineered from the Kelvinator/Electrolux Android APK (com.kelvinator.airconditioner),
the bundled `libNetworkAPI.so` (x86-64 DNA SDK build, runs on Linux via a shim),
and the **decrypted DNA Kit Lua script** for pid `9b4f0000`.

## Architecture

```
Cloud API (HTTPS)                        Device control path
├── account/login (bizaccount)           ├── DNA SDK (libNetworkAPI.so)
├── ec4/v1/common/api  → API key         │   SDKInit → SDKAuth (TLS+ECDH)
├── user/getfamilyid                     │   dnaControl → cloud relay
└── family/getallinfo → did, mac,        │       {prefix}access.ibroadlink.com:1998
                        aes_key, password │   or local UDP (requires session key)
                                          ├── DNA Kit Lua script (pid 9b4f0000)
                                          │   defines param names + payload format
                                          └── plaintext payload:
                                              [a5a55a5a][ck:2][cmd][0x0b][len:2][ver:2][JSON]
```

## Wire Payload (GROUND TRUTH — from the DNA Kit script)

The payload that rides inside the Broadlink 0x38-header/AES packet:

```
[0:4]   a5 a5 5a 5a   magic
[4:6]   checksum LE   sum(bytes) with [4:6] zeroed, seed 0xBEAF
[6]     0x01 = get, 0x02 = set
[7]     0x0b          protocol tag
[8:10]  body len LE
[10:12] version LE    (0)
[12:]   JSON body
```

Request body: `{"<param>": <val>, ..., "did": "<did>"}` — params are DNA Kit
STRING names: `ac_pwr, ac_mode, temp, ac_mark, ac_vdir, ac_hdir, ac_slp,
scrdisp, ecomode, envtemp (RO), ac_errcode (RO), tempunit, anionmode, drmode,
espmode, filreset, insectrepellent, mldprf, qtmode, timer, ac_timingtime,
modelnumber, sn, …` (full list: `kelvinator_dna/protocol.py::DNA_KIT_PARAMS`).

Source of truth: `custom_components/kelvinator/kelvinator_dna/protocol.py`
(self-checks against live SDK output).

## Encryption

- **Device path**: AES-128-CBC, IV `562e17996d093d28ddb3ba695a2e6f58`, PKCS7,
  key = per-device cloud `aes_key`. Payload checksum inside ciphertext at [4:6].
- **Cloud family API**: AES-128-CBC, IV `EA AA AA 3A BB 58 62 A2 19 18 B5 77 1D 16 15 AA`,
  zero-pad to `(len//16 + 2) * 16`, key from `/ec4/v1/common/api`.
- **Checksums**: device payload = sum(bytes, 0xBEAF) (`bl_getcsum`);
  cloud relay = Fletcher-16 seeds (5,10) (`bl_sdk_getsum`).

## Cloud API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `{license}bizaccount.ibroadlink.com/account/login` | User authentication |
| `{license}bizihcv0.ibroadlink.com/ec4/v1/common/api` | API key + timestamp |
| `{license}bizihcv0.ibroadlink.com/ec4/v1/user/getfamilyid` | Family IDs |
| `{license}bizihcv0.ibroadlink.com/ec4/v1/family/getallinfo` | Devices + AES keys |
| `{prefix}access.ibroadlink.com:1998` | DNA control relay (SDK) |
| `{license}auth.ibroadlink.com` | DNA SDKAuth (TLS/ECDH session) |

## Critical Finding: Locked Devices

These Kelvinator ACs reject the classic Broadlink local auth handshake with
**errno -7 ("control key is expired")** — verified with live captures of the
exact packets the official app sends (0x65 auth, default key, device_id 0).
Local control requires a cloud-issued control key obtained via the SDK's
`SDKAuth` (TLS + ECDH) flow. The integration therefore drives the vendor SDK
binary (`dna_sdk/`) for control; pure-Python local UDP is impossible without
reimplementing SDKAuth.

## libNetworkAPI.so on Linux

The shipped SO is the SDK's **x86-64** build (DNASDK/linux, version
`2.0.49-6566c07`). It runs on glibc with:
- fake `JNIEnv` vtable (GetStringUTFChars/NewStringUTF pass-through)
- bionic symbol shims: `__android_log_*`, `__sF`, `__errno`, `__assert2`
- ELF tweaks: verneed `LIBC`/`LIBM` entries marked WEAK; INIT_ARRAYSZ=0

Wrapped by `dna_sdk/kelvinator_native.so` (built from `native_wrap.c`,
compile: `gcc -shared -fPIC -o kelvinator_native.so native_wrap.c -L. -l:libNetworkAPI.so -w`)
and driven as a subprocess by `dna_bridge.py`.

`dnaControl` JSON contract (validated against the SO):
- devInfo: `{did, mac ("aa:bb:.."), aes_key, password, pid, devtype, magiccode, ip, port}`
- subDevInfo: `{did, pid, name}`
- data: `{"act":"get"|"set","params":[names],"vals":[[{"val":n}], ...]}` (sizes must match)
- desc: `{"name":"dev_ctrl"|"dev_data","command":same,"cookie":"<hex>"}`

`dev_data` (build-only) returns `data.ctrldata` base64; `dev_ctrl` relays via
the cloud (needs SDKAuth session; prefix `0access...` fails DNS otherwise).

## Key files

- `custom_components/kelvinator/kelvinator_dna/protocol.py` — payload format + self-check
- `custom_components/kelvinator/dna_sdk/` — SDK binary, shim, bridge, DNA Kit script
- `custom_components/kelvinator/dna_native.py` — async bridge client
- `working_doco/uncertainty_audit.md` — assumption ledger (mostly resolved)
- `testing/test_lan.py` — live LAN test harness
- `tests/local_control_feasibility.md` — why local-only control is blocked