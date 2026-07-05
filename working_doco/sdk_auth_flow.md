# SDK Authentication Flow (`bl_sdk_auth`)

> From `libNetworkAPI.so` binary analysis — full TLS + ECDH + X.509 certificate auth stack.

## Function Overview

### JNI Entry Point
`Java_cn_com_broadlink_networkapi_NetworkAPI_bl_1sdk_1auth` at 0x001c130 (3037 bytes)

JNI signature from decompiled `NetworkAPI.java`:
```java
public static native String bl_sdk_auth(
    String license,          // OEM license ID
    String companyId,        // Company identifier
    String appName,          // App package name
    String appVersion,       // App version string
    String deviceName,       // Device model name
    String deviceMac,        // Device MAC address
    String deviceDid,        // Device ID
    String devicePid,        // Product ID
    String userId,           // Cloud user ID
    String loginSession,     // Login session token
    String apiKey,           // API key from /ec4/v1/common/api
    String timestamp,        // Server timestamp
    String sdkVersion        // SDK version string
);
```

### Internal Auth Engine
`networkapi_auth` at 0x00cbfa0 (8002 bytes — the largest function in the binary)

## Crypto Primitives Used

### TLS/SSL Stack
| Symbol | Purpose |
|---|---|
| `broadlink_ssl_init` | Initialize SSL context |
| `broadlink_ssl_conf_authmode` | Set client/server auth mode |
| `broadlink_ssl_conf_ciphersuites` | Configure cipher suites |
| `broadlink_ssl_config_init` | Initialize SSL config |
| `broadlink_ssl_session_init` | Initialize SSL session |
| `broadlink_ssl_parse_change_cipher_spec` | TLS handshake |
| `broadlink_ssl_optimize_checksum` | TLS record checksums |
| `broadlink_cipher_list` | List available ciphers |
| `broadlink_cipher_supported` | Global cipher support flags |

### ECDH Key Exchange
| Symbol | Purpose |
|---|---|
| `broadlink_ecdh_init` | Initialize ECDH context |
| `broadlink_ecp_gen_keypair` | Generate EC keypair |
| `broadlink_ecp_point_init` | Initialize EC point |
| `broadlink_ecp_group_init` | Initialize EC group |
| `broadlink_ecp_keypair_init` | Initialize EC keypair |

### ECDSA Signatures
| Symbol | Purpose |
|---|---|
| `broadlink_ecdsa_init` | Initialize ECDSA context |
| `broadlink_ecdsa_from_keypair` | Derive ECDSA from keypair |

### X.509 Certificates
| Symbol | Purpose |
|---|---|
| `broadlink_x509_crt_init` | Initialize X.509 certificate |
| `broadlink_x509_crl_init` | Initialize certificate revocation list |
| `broadlink_x509_csr_init` | Initialize certificate signing request |
| `broadlink_x509write_crt_init` | Write X.509 certificate |
| `broadlink_x509write_csr_init` | Write CSR |

### PK Encryption
| Symbol | Purpose |
|---|---|
| `broadlink_pk_init` | Initialize PK context |
| `broadlink_pk_encrypt` | Public-key encrypt |
| `broadlink_pk_decrypt` | Public-key decrypt |

### Cipher (AES) for Auth
| Symbol | Purpose |
|---|---|
| `broadlink_cipher_init` | Initialize cipher context |
| `broadlink_cipher_setup` | Configure cipher (AES-CBC) |
| `broadlink_cipher_set_padding_mode` | Set padding mode |
| `broadlink_cipher_setkey` | Set encryption key |
| `broadlink_cipher_set_iv` | Set IV |
| `broadlink_cipher_auth_encrypt` | Encrypt with auth tag |
| `broadlink_cipher_auth_decrypt` | Decrypt + verify auth tag |
| `broadlink_cipher_definitions` | Global cipher parameter table |

### DRBG / Entropy
| Symbol | Purpose |
|---|---|
| `broadlink_ctr_drbg_init` | CTR-DRBG random generator |
| `broadlink_hmac_drbg_init` | HMAC-DRBG random generator |
| `broadlink_havege_init` | HAVEGE entropy collector |
| `broadlink_entropy_init` | Entropy source init |

### Hashing
| Symbol | Purpose |
|---|---|
| `broadlink_fo_init` | Full-domain hash |
| `broadlink_fo5_init` | FO5 variant |
| `networkapi_hash_init` | SDK-internal hash init |

### Token Management
| Symbol | Purpose |
|---|---|
| `networkapi_token_init` | Initialize session token |
| `networkapi_enc2b_init` | Encrypted binary blob init |
| `networkapi_enc2b_init_key` | Set encryption key for blob |
| `networkapi_enc2b_init_param` | Set parameters for blob |

### Global State
| Symbol | Value | Purpose |
|---|---|---|
| `globalauth` | 0x135050 (BSS) | Global auth state struct |
| `isEnableDeviceRemoteControl` | 0x132c80 (BSS) | Remote control enable flag |

## Auth Flow (Reconstructed)

Based on function call graph and symbol relationships:

```
bl_sdk_auth(13 params)
  │
  ├─ networkapi_auth(device_info, license_info, session_info)
  │   │
  │   ├─ broadlink_ssl_init()           // Initialize TLS
  │   ├─ broadlink_ssl_conf_authmode()  // Client certificate auth
  │   ├─ broadlink_ecdh_init()          // ECDH key exchange
  │   │   ├─ broadlink_ecp_gen_keypair()
  │   │   └─ broadlink_ecdsa_from_keypair()
  │   ├─ broadlink_x509_crt_init()      // Load device certificate
  │   ├─ broadlink_pk_encrypt()         // Encrypt session data
  │   ├─ broadlink_cipher_auth_encrypt() // AEAD encrypt
  │   │
  │   ├─ networkapi_hash_init()         // Hash device identity
  │   ├─ networkapi_token_init()        // Generate session token
  │   └─ networkapi_enc2b_init()        // Encrypt token blob
  │       ├─ networkapi_enc2b_init_key()
  │       └─ networkapi_enc2b_init_param()
  │
  └─ returns JSON: {status, token, session_key, expires}
```

## Parameter Semantics

| # | Java Name | Semantic | Example |
|---|-----------|----------|---------|
| 1 | license | OEM license ID (32-char hex) | `bddb4af53f74edaa03b1aa439b75e7a6` |
| 2 | companyId | Company identifier (16-char hex) | `98273b1f0638bc78...` |
| 3 | appName | Android package name | `com.kelvinator.airconditioner` |
| 4 | appVersion | App version code | `203` |
| 5 | deviceName | Device model name | `SM-S926B` |
| 6 | deviceMac | Device MAC address | `a1:b2:c3:d4:e5:f6` |
| 7 | deviceDid | BroadLink device ID | (from cloud) |
| 8 | devicePid | Product ID | `9b4f0000` |
| 9 | userId | Cloud user ID | (from login) |
| 10 | loginSession | Login session token | (from login) |
| 11 | apiKey | API key | (from /ec4/v1/common/api) |
| 12 | timestamp | Server timestamp | (from /ec4/v1/common/api) |
| 13 | sdkVersion | SDK version string | `2.5.16` |

## Key Derivation

The auth flow generates:
1. **ECDH shared secret** — from device + server EC keypairs
2. **Session key** — derived from ECDH secret + hashed identity
3. **Auth token** — encrypted blob containing session key + expiry + device identity
4. **Renewal token** — for session refresh without full re-auth

## Session Lifecycle

```
Login (account/login)
  → Get userid + loginsession
     → /ec4/v1/common/api (get API key + timestamp)
        → bl_sdk_auth (establish session)
           → Returns: {token, session_key, expires}
              → Use token for all subsequent API calls
                 → Token expires → bl_sdk_auth again with renewal token
```

## TLS Configuration

The binary contains a full TLS 1.2 stack (mbedTLS-based, renamed symbols):
- Cipher suites configured via `broadlink_ssl_conf_ciphersuites`
- Auth mode: client certificate (`broadlink_ssl_conf_authmode`)
- Certificate chain: device cert → OEM intermediate → BroadLink root

## Existing Workspace Impacts

### Not Implemented
The Python workspace does NOT implement the SDK auth flow. Instead:
- `api.py::_cloud_login_sync()` does account/login (step 1)
- `cloud.py::KelvinatorCloud.authenticate()` does /ec4/v1/common/api (step 2)
- **No code calls bl_sdk_auth** (step 3)

### Why It Works Without bl_sdk_auth
- The Python integration uses cloud API endpoints directly with `loginsession` + `userid`
- The family API (`/ec4/v1/family/*`) accepts these direct credentials
- Device credential retrieval (AES keys from `/family/getallinfo`) works without full SDK auth
- The SDK auth is only needed for the native `libNetworkAPI.so` cloud relay path

### Implications
- As long as the Python integration uses local UDP via `broadlink_api/` (NOT cloud relay),
  the SDK auth flow is unnecessary
- If cloud relay support is ever added, bl_sdk_auth would need to be reimplemented
- The crypto stack needed would be: ECDH (P-256), ECDSA, X.509 cert parsing, AES-GCM
- All of these are available in Python (`cryptography` library) but the full auth flow
  has 8000+ bytes of native code — reimplementation would be substantial

## Security Considerations

1. **Client certificates**: The binary embeds a device certificate. Replicating the auth
   flow in Python would require extracting or generating this certificate.
2. **ECDH keypair**: Generated per-session. Python `cryptography` can do this.
3. **Token storage**: The native code stores tokens in encrypted blobs (`enc2b`).
   Python should use HA's secure storage (`homeassistant.helpers.storage`).
4. **Session renewal**: Handled by `networkapi_token_init`. Token expiry is embedded
   in the encrypted token blob.

## Recommendation

**DO NOT reimplement bl_sdk_auth.** The existing Python integration works without it by:
1. Using account/login for initial auth
2. Using family API for device discovery
3. Using local UDP (planned) for device control

Only reimplement if cloud relay support (remote access via BroadLink servers) is
required after local UDP is fully working.
