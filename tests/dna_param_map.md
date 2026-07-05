# DNA Protocol Parameter Map

> Extracted from `libNetworkAPI.so` x86-64 binary disassembly (symbol-preserved, NDK r16b).

## Core TFB Functions

### `bl_sdk_tfb_encode`
```
int bl_sdk_tfb_encode(uint8_t *dst, int data_len, int buf_capacity, 
                       uint8_t *key, uint8_t *data)
```
- **Padding**: PKCS7 (pad-byte value = number of pad bytes, matching RFC 5652 Section 6.3)
- Verifies `data_len + pad_size ≤ buf_capacity`, returns -1 on overflow
- Calls `broadlink_tfb_setkey_enc(key, 0x80)` → AES-128 key (0x80 bits)
- Calls `broadlink_tfb_crypt_fef(mode=1, ...)` → encrypt
- Returns total output size (data_len + pad)

### `bl_sdk_tfb_decode`
```
int bl_sdk_tfb_decode(uint8_t *dst, int data_len, uint8_t *key, uint8_t *data)
```
- Validates `data_len % 16 == 0` (must be block-aligned)
- Calls `broadlink_tfb_setkey_dec(key, 0x80)` → AES-128
- Calls `broadlink_tfb_crypt_fef(mode=0, ...)` → decrypt
- Validates PKCS7: reads last byte as `pad_len`, verifies all N trailing bytes == `pad_len`
- Returns `data_len - pad_len` on success, -1 on padding error

### `bl_sdk_getsum`
```
uint32_t bl_sdk_getsum(uint8_t *data, int len)
```
- **Fletcher-16 variant** with seeds `(5, 10)` instead of standard `(0, 0)`
- Returns `(sum2 << 16) | sum1` — 32-bit combined checksum
- Algorithm:
  ```c
  uint16_t sum1 = 5, sum2 = 10;
  for (int i = 0; i < len; i++) {
      sum1 = (sum1 + data[i]) & 0xFFFF;
      sum2 = (sum2 + sum1) & 0xFFFF;
  }
  return (sum2 << 16) | sum1;
  ```

## Parameter IDs

The TFB payload format in the binary is:
```
[did: N bytes]        — Device identifier
[sub_device_id: 2 LE] — Sub-device index  
[command_type: 1]     — 0x01=set, 0x02=query
[param_id:1][len:1][val:N] — Repeated parameter blocks
```

**⚠️ WARNING**: The parameter ID → semantic mapping below was inferred from the decompiled
Android app (`DevConstants.java`, `ACCommonUtils.java`) and binary structure analysis.
These IDs have NOT been validated against live device traffic. The binary's
`networkapi_dna_control` function (0xdd600, 3837 bytes) contains the param-ID dispatch
logic but the mapping is embedded in control flow, not a lookup table.

### Confirmed from DevConstants.java (app-level string keys)

| TFB Param ID | DevConstants.java Name | Semantic | App Values |
|---|---|---|---|
| 0x01 | `ac_pwr` (DEV_POWER) | Power state | 0=off, 1=on |
| 0x02 | `ac_mode` (DEV_MODE) | Operation mode | 0=cool, 1=heat, 2=dry, 3=fan, 4=auto, 5=eco, 6=eight_heat, 7=twelve_heat |
| 0x03 | `temp` (DEV_TEMP) | Target temperature | 16-30°C |
| 0x04 | `ac_mark` (DEV_FAN_MARK) | Fan speed | 0=auto, 1=low, 2=med, 3=high, 4=turbo, 5=quiet, 6=low_med, 7=med_high |
| 0x05 | `ac_vdir` (DEV_FAN_VDIR) | Vertical swing | 0=off, 1=on |
| 0x06 | `ac_slp` (DEV_MODE_SLEEP) | Sleep mode | 0=off, 1=on |
| 0x07 | — | Turbo toggle | (may be unused — turbo is fan speed 4) |
| 0x08 | `tempunit` (DEV_TEMP_UNIT) | Temperature unit | 0=°C, 1=°F |
| 0x09 | `envtemp` (DEV_ENV_TEMP) | Ambient/room temp | (read-only) |
| 0x0a | `ac_errcode` (DEV_ERROR_CODE) | Error code | (read-only) |
| 0x0b | `scrdisp` (DEV_SCREEN_DISPLAY) | Display brightness | 0=off, 1=on |

### Additional Parameters from DevConstants.java (NOT in protocol.py)

| TFB Param ID (unknown) | DevConstants Name | Description |
|---|---|---|
| ? | `ac_hdir` (DEV_FAN_HDIR) | Horizontal swing |
| ? | `timer` (DEV_TIMER) | Timer setting |
| ? | `ac_timingtime` (DEV_TIMING) | Schedule timing |
| ? | `ac_timingenable` (DEV_TIMING_ENABLE) | Schedule enable |
| ? | `modelnumber` (DEV_MODEL_NUMBER) | Model number |
| ? | `sn` (DEV_SN) | Serial number |
| ? | `ecomode` (DEV_MODE_ECO) | Eco mode toggle |
| ? | `qtmode` (DEV_MODE_QT) | Quiet mode |
| ? | `ac_clean` (DEV_MODE_CLEAN) | Self-clean mode |
| ? | `mldprf` (DEV_MODE_MOULD_PROOF) | Mould-proof mode |
| ? | `anionmode` (DEV_MODE_ANION) | Anion/ionizer mode |
| ? | `drmode` (DEV_MODE_DR) | Demand response mode |
| ? | `drtime` (DEV_MODE_DRTIME) | DR time |
| ? | `espmode` (DEV_MODE_ESP) | ESP mode |
| ? | `disimode` (DEV_MODE_DISI) | Disinfection mode |
| ? | `DEV_HEALTH` | Health mode |
| ? | `filreset` (DEV_FILRESET) | Filter reset |
| ? | `smarteyes` (DEV_SMART_EYE) | Smart eye sensor |
| ? | `insectrepellent` (DEV_MOSQUITO) | Mosquito repellent |
| ? | `coldplasma` (DEV_COLDPLASMA) | Cold plasma |
| ? | `ac_compressorstatus` | Compressor status (read-only) |
| ? | `ac_fourwayvalvestatus` | 4-way valve status (read-only) |
| ? | `ac_heaterstatus` | Heater status (read-only) |
| ? | `ac_indoorfanstatus` | Indoor fan status (read-only) |
| ? | `ac_evapordefroststate` | Defrost state (read-only) |
| ? | `upload_enable` | Cloud upload enable |

### Display Flag Parameters (model-specific feature toggles)
These control which UI features are offered based on model P/N:

| DevConstants Name | Purpose |
|---|---|
| `ecodisplay` | Show/hide ECO mode |
| `8cdisplay` | Show/hide 8°C heat mode |
| `healthdisplay` | Show/hide health mode |
| `lightdisplay` | Show/hide display light |
| `markdisplay` | Show/hide fan speed marks |
| `mldprfdisplay` | Show/hide mould-proof |
| `silencedisplay` | Show/hide silence/quiet |
| `slpdisplay` | Show/hide sleep mode |
| `ac_settempinauto` | Allow temp set in auto mode |
| `ac_setmarkindehum` | Allow fan set in dry mode |
| `ac_settempindehum` | Allow temp set in dry mode |
| `ac_setautomarkinauto` | Allow auto-fan in auto mode |
| `ac_setautomarkinfan` | Allow auto-fan in fan mode |
| `ac_setecoinauto` | Allow eco in auto mode |
| `ac_setecoonlyincool` | Eco only in cool mode |
| `ac_setecoindehum` | Allow eco in dry mode |
| `ac_setsleepinfan` | Allow sleep in fan mode |
| `ac_setslpindehum` | Allow sleep in dry mode |
| `ac_setmarkinauto` | Allow fan set in auto mode |
| `ac_setquietinallmode` | Allow quiet in all modes |
| `ac_setsch_markin8_12_heat` | Allow fan set in 8-12°C heat |
| `setsleepinauto` | Allow sleep in auto mode |
| `ac_type` | AC type identifier |

## Existing Workspace Impacts

### ✅ Correct
- `protocol.py` param IDs 0x01-0x0b match DevConstants.java
- `const.py` AcMode and FanSpeed enum values match ACCommonUtils.java
- `api.py` uses correct param names (`ac_pwr`, `ac_mode`, etc.)

### ❌ Needs Fix
1. **PKCS7 vs Zero-Padding**: `broadlink_api/crypto.py` uses zero-padding but the SO uses PKCS7!
   - Impact: Local UDP payloads will fail decryption if device expects PKCS7 padding
   - Fix: Change `crypto.py` to use PKCS7 padding (pad-byte = pad-count)

2. **Checksum**: Current `broadlink_api/protocol.py` uses a simple 2-byte little-endian sum with seed 0xBEAF.
   The SO uses Fletcher-16 with seeds (5, 10). These are DIFFERENT algorithms.

3. **Missing params**: ~30 param IDs from DevConstants.java have no protocol.py mapping.
   Most are model-specific features. `ac_hdir` (horizontal swing) is the most impactful
   missing param.

### ⚠️ Param ID Uncertainty
The exact wire-level param ID values (0x01-0x0b) are **inferred** from binary structure
analysis, not verified against live traffic. `networkapi_dna_control` (0xdd600) contains
the dispatch logic but the mapping between app-level string keys and wire-level byte IDs
is encoded in control flow. Frida hooking is recommended for verification.
