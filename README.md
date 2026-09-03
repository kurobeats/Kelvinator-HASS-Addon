# Kelvinator Home Comfort

[![GitHub Release][release-shield]][release]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![hacs][hacsbadge]][hacs]

Home Assistant integration for controlling Kelvinator/Electrolux air conditioners via the BroadLink DNA protocol.

## Features

- **Climate entity** — Thermostat card with mode, temperature, fan speed, and swing control
- **Switch entities** — Per-AC toggles for power, display, sleep, and ECO modes
- **Sensor entities** — Ambient temperature and error code per device
- **Single-step setup** — Enter your Kelvinator app username and password; devices are auto-discovered from your cloud account
- **Vendor SDK control** — Device control/status runs through the official BroadLink DNA SDK (`libNetworkAPI.so`) shipped inside this integration, using the same DNA Kit protocol scripts as the Kelvinator mobile app

## Supported Devices

- Kelvinator/Electrolux split-system air conditioners registered with the Kelvinator mobile app
- BroadLink DNA protocol AC units (devtype 20379 / `0x4F9B`, pid `9b4f0000`)

## Requirements

| Requirement | Why |
|---|---|
| Kelvinator cloud account | Same email/phone and password used in the mobile app |
| Home Assistant 2024.1+ | Integration framework |
| **x86-64 Linux** | The bundled DNA SDK binary is an x86-64 Android-NDK build; other architectures are not supported yet |
| `pycryptodome` ≥ 3.19.0 | AES encryption for cloud login (installed automatically) |

## How Control Works

These ACs are **locked** BroadLink DNA devices. They reject the classic
local UDP auth handshake (errno -7, "control key is expired") — even the
official app does this — and require a cloud-issued control key via the
DNA SDK's `SDKAuth` (TLS + ECDH) flow. This integration therefore uses
the vendor's own SDK binary for the auth/control path:

1. **Login** — Authenticates against `bizaccount.ibroadlink.com` using AES-128-CBC encrypted credentials (matching the mobile app's login flow)
2. **Discovery** — Retrieves device list, AES keys, and passwords from `bizihcv0.ibroadlink.com` via the bundled `kelvinator_dna.cloud` module
3. **DNA SDK init** — Starts the bundled DNA SDK (subprocess bridge) with the DNA Kit script for pid `9b4f0000`
4. **SDKAuth** — Registers the cloud session with the DNA cloud (ECDH handshake) so devices accept our control key
5. **Control/status** — `dnaControl` cloud-relay requests via the SDK; the plaintext wire payload is `[a5a55a5a][ck][cmd][0x0b][len][ver][JSON]` with DNA Kit parameter names (see `kelvinator_dna/protocol.py`)

## Installation (HACS)

1. In Home Assistant, go to **HACS → Integrations**
2. Click the **⋮** menu → **Custom repositories**
3. Paste `https://github.com/kurobeats/Kelvinator-HASS-Addon` as the repository URL, select type **Integration**
4. Click **Add**, then find **Kelvinator Home Comfort** and click **Download**
5. Restart Home Assistant

## Installation (Manual)

1. Copy `custom_components/kelvinator/` into your HA config's `custom_components/` directory
2. Restart Home Assistant

## Configuration

Single-step setup via the Home Assistant UI:

1. Go to **Settings → Devices & Services** → **Add Integration**
2. Search for **Kelvinator Home Comfort** and select it
3. Enter your credentials:
   - **Username** — Email or phone number used in the Kelvinator app
   - **Password** — Kelvinator app password
   - **Country Code** — `61` for Australia, `64` for New Zealand (default: `61`)
   - **Poll Interval** — State refresh interval in seconds (default: `30`)
4. Click **Submit**

Devices are automatically discovered from your cloud account — no IP addresses or manual pairing required.

## Exposed Entities

Each AC unit creates these entities:

| Platform | Entity | Purpose |
|---|---|---|
| Climate | `climate.kelvinator_xxxx` | Thermostat card (mode, temp, fan, swing) |
| Switch | `switch.kelvinator_xxxx_power` | Power on/off |
| Switch | `switch.kelvinator_xxxx_display` | Front panel display toggle |
| Switch | `switch.kelvinator_xxxx_sleep` | Sleep mode |
| Switch | `switch.kelvinator_xxxx_eco` | ECO energy-saving mode |
| Sensor | `sensor.kelvinator_xxxx_ambient_temperature` | Room temperature (°C) |
| Sensor | `sensor.kelvinator_xxxx_error_code` | Device error code |

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Home Assistant                                   │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Kelvinator Integration                        │ │
│  │                                              │ │
│  │  config_flow.py → coordinator.py             │ │
│  │        │                                      │ │
│  │  api.py (cloud login + discovery)            │ │
│  │        │                                     │ │
│  │  dna_native.py  ──►  dna_sdk/dna_bridge.py   │ │
│  │  (async bridge)       (subprocess, stdlib)   │ │
│  │                          │                    │ │
│  │                 kelvinator_native.so          │ │
│  │                          │                    │ │
│  │                 libNetworkAPI.so (x86-64)     │ │
│  │                 + DNA Kit script (pid 9b4f)   │ │
│  └──────────────────────┬────────────────────────┘ │
└──────────────────────┬───┴──────────────────────────┘
                       │ HTTPS / TCP relay
                       ▼
   ┌─────────────────────────────────────────────┐
   │ BroadLink Cloud                              │
   │  ├─ bizaccount.ibroadlink.com  (login)       │
   │  ├─ bizihcv0.ibroadlink.com    (discovery)   │
   │  └─ access.ibroadlink.com:1998 (ctrl relay)  │
   └─────────────────────────────────────────────┘
```

## Troubleshooting

### Login fails during setup (`-1008`)

- Verify you're using the **same credentials** as the Kelvinator mobile app
- If using a phone number, the integration sends it as-is; the account must be a phone account
- `-1005` usually means the username field type was wrong (email vs phone)

### No devices discovered

- Log into the Kelvinator app on your phone and verify your AC units appear there
- The integration can only discover devices registered to your cloud account

### Commands rejected ("control key expired")

- The DNA SDK's `SDKAuth` step registers your session with the BroadLink cloud.
  Check the HA logs for the `DNA SDKAuth:` line at setup.
- If SDKAuth failed, control will be rejected until it succeeds.

### Platform support

- The bundled SDK binary is **x86-64 only** (matching the official app's
  x86_64 build). On ARM hosts (e.g. Raspberry Pi) control is disabled;
  an arm64 build of the same SDK may be bundled later.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

Licensed under the GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.
The bundled `libNetworkAPI.so` and DNA Kit script are proprietary BroadLink SDK
components included for interoperability with devices the user owns.

---

[release-shield]: https://img.shields.io/github/v/release/kurobeats/Kelvinator-HASS-Addon.svg
[release]: https://github.com/kurobeats/Kelvinator-HASS-Addon/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/kurobeats/Kelvinator-HASS-Addon.svg
[commits]: https://github.com/kurobeats/Kelvinator-HASS-Addon/commits/main
[license-shield]: https://img.shields.io/github/license/kurobeats/Kelvinator-HASS-Addon.svg
[license]: LICENSE
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg