# Ghidra RE Findings: libNetworkAPI.so

## Setup

MCP server config in `.pi/mcp.json`:
```json
{
  "mcpServers": {
    "ghidra-mcp-http": {
      "url": "http://192.168.1.50:8081/mcp"
    }
  }
}
```

Server at `192.168.1.50:8081`, requires `Host: localhost:8081` header. Accepts SSE.

## Target Binary

`custom_components/kelvinator/libNetworkAPI.so`
- Format: ELF 64-bit LSB shared object, x86-64
- Built: Android NDK r16b, API 21
- Status: **Stripped** (no symbol table)
- Size: 1,254,616 bytes

5 arch variants in decompiled APK:
- `arm64-v8a/libNetworkAPI.so` — 1,188,776 bytes
- `armeabi-v7a/libNetworkAPI.so` — 871,564 bytes
- `armeabi/libNetworkAPI.so` — 928,908 bytes
- `x86/libNetworkAPI.so` — 1,498,188 bytes
- `x86_64/libNetworkAPI.so` — 1,254,616 bytes

## JNI Exports (from decompiled Java)

Source: `cn/com/broadlink/networkapi/NetworkAPI.java` (decompiled from APK)

```java
public class NetworkAPI {
    public static native int SDKInit(String configJson);
    public static native String dnaControl(String devInfo, String subDevInfo, String data, String cmdDesc);
    public static native int devicePair(String did, String config);
    public static native String deviceStatusOnServer(String config, String did);
    public static native String deviceProbe(String did);
    public static native String deviceProfile(String did, String pid, String version);
    public static native String LicenseInfo(String license);
    // ... and more
}
```

## Key Functions to Analyze

### 1. `dnaControl` (HIGHEST PRIORITY)
The main device control function. Takes 4 JSON string arguments:
- `devInfo`: Device credentials (did, mac, aes_key, password)
- `subDevInfo`: Sub-device info (usually empty string "")
- `data`: Control payload JSON
- `cmdDesc`: Command type ("dev_ctrl" for control, "dev_status" for status)

**Known unknowns**:
- How does the SO build the TFB payload from the JSON `data` argument?
- What param ID → value mapping does it use?
- Does it do AES-CBC encryption internally or delegate to a separate routine?

### 2. `SDKInit`
Initialization. Takes one JSON config string. Sets up internal state.

### 3. `deviceStatusOnServer`
Cloud relay status query. Takes device config JSON + did string. Returns status JSON.

### 4. `bl_sdk_auth`
Complex auth routine with 13 string params. Not yet reverse-engineered. Contains:
- App metadata (package name, version)
- Device info (model, manufacturer)
- License ID
- API key

## Encryption Routines (from decompiled Java)

The SO handles wire encryption internally. Java-side encryption is for storage only:

### AesUtils.java
```java
// AES/CBC/PKCS5Padding with SHA1PRNG keygen
// Used for: SharedPreferences encryption (BLUserInfoUint)
// NOT used for DNA wire encryption
public static byte[] aesEncrypt(byte[] content) { ... }
public static byte[] aesDecrypt(byte[] content) { ... }
```

### EncryptUtil.java
```java
// AES/ECB/PKCS5Padding
// Used for: SecuritySharedPreference (device-serial-keyed)
// NOT used for DNA wire encryption
```

### BLCommonTools.java (Broadlink SDK)
```java
// AES/CBC/ZeroBytePadding — DNA wire encryption
public static byte[] aesNoPadding(byte[] key, byte[] data, byte[] iv) { ... }
// AES/CBC/PKCS7Padding — DNA wire decryption
public static byte[] aesPKCS7PaddingDecryptToByte(byte[] key, byte[] data, byte[] iv) { ... }
```

## Ghidra Analysis Strategy

Since the SO is **stripped**, Ghidra cannot recover function names. Strategy:

1. **Find JNI exports by string name** — Ghidra can locate functions registered via `RegisterNatives` or exported with `Java_` prefix
2. **Cross-reference string constants** — Look for known hex strings (DID format, JSON keys) in .rodata
3. **Trace `dnaControl` → encryption calls** — Follow call graph from JNI entry to any AES/CBC calls
4. **Identify TFB packet builder** — Look for loops that write `[id:1][len:1][val:N]` patterns

## What We Already Know (from pure-Python RE)

- DNA header: 0x38 bytes with magic, devtype=0x4F9B, MAC, device_id
- Encryption: AES-128-CBC, Broadlink IV, zero-padding, 2-byte checksum prepended
- TFB payload: [did:16][sub:2 LE][cmd:1][params...]
- Auth flow: CMD_AUTH (0x65) → get device_id → update_key(cloud_key)

## What We Still Need from Ghidra

1. **Param ID mapping confirmation** — Are 0x01-0x0b the correct wire-level IDs?
2. **Cloud relay protocol** — How does `deviceStatusOnServer` construct cloud relay packets?
3. **SDK auth flow** — What does `bl_sdk_auth` do with its 13 params?

## Verification Plan

Preferred approach: **Frida hooking** on Android emulator (faster than Ghidra for ground truth):

```javascript
// Frida script to hook dnaControl
Java.perform(function() {
    var NetworkAPI = Java.use("cn.com.broadlink.networkapi.NetworkAPI");
    NetworkAPI.dnaControl.implementation = function(devInfo, subDevInfo, data, cmdDesc) {
        console.log("dnaControl called:");
        console.log("  devInfo: " + devInfo);
        console.log("  subDevInfo: " + subDevInfo);
        console.log("  data: " + data);
        console.log("  cmdDesc: " + cmdDesc);
        var result = this.dnaControl(devInfo, subDevInfo, data, cmdDesc);
        console.log("  result: " + result);
        return result;
    };
});
```

This would provide exact parameter values for every control operation.
