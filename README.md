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
- **Self-contained** — The reverse-engineered protocol library is bundled directly in the integration; no unpublished dependencies

## Supported Devices

- Kelvinator/Electrolux split-system air conditioners registered with the Kelvinator mobile app
- BroadLink DNA protocol AC units (devtype 20379 / `0x4F9B`, pid `9b4f0000`)

## Requirements

| Requirement | Why |
|---|---|
| Kelvinator cloud account | Same email/phone and password used in the mobile app |
| Home Assistant 2024.1+ | Integration framework |
| `pycryptodome` ≥ 3.19.0 | AES encryption for cloud login (installed automatically) |

The `kelvinator_dna` protocol library is **bundled** in this integration — no extra pip packages or unpublished dependencies needed.

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
│  │  ┌───────────────┐  ┌────────────────────┐  │ │
│  │  │ config_flow.py│  │  coordinator.py    │  │ │
│  │  │ (UI login)    │  │  (poll/refresh)    │  │ │
│  │  └───────┬───────┘  └────────┬───────────┘  │ │
│  │          │                   │               │ │
│  │  ┌───────▼───────────────────▼────────────┐  │ │
│  │  │ api.py                                  │  │ │
│  │  │  ├─ KelvinatorCloudClient               │  │ │
│  │  │  │   ├─ _cloud_login_sync()             │  │ │
│  │  │  │   │   → bizaccount.ibroadlink.com    │  │ │
│  │  │  │   └─ _cloud_discover_sync()          │  │ │
│  │  │  │      → kelvinator_dna.cloud          │  │ │
│  │  │  │         → bizihcv0.ibroadlink.com    │  │ │
│  │  │  ├─ KelvinatorACDevice                  │  │ │
│  │  │  │   └─ send_command / update_state     │  │ │
│  │  │  └─ DNACloudRelay (optional)            │  │ │
│  │  │      └─ kelvinator_dna.so_bridge        │  │ │
│  │  │         → libNetworkAPI.so               │  │ │
│  │  └──────────────────┬──────────────────────┘  │ │
│  │                     │                         │ │
│  │  ┌──────────────────▼──────────────────────┐  │ │
│  │  │ climate.py / switch.py / sensor.py       │  │ │
│  │  └─────────────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────┘ │ │
└──────────────────────┬───────────────────────────┘ │
                       │ HTTPS (Cloud API)            │
                       ▼                              │
   ┌─────────────────────────────────────────────┐   │
   │ BroadLink Cloud                              │   │
   │  ├─ bizaccount.ibroadlink.com               │   │
   │  │   → Account login (AES-encrypted)         │   │
   │  ├─ bizihcv0.ibroadlink.com                 │   │
   │  │   → Device discovery, AES keys, passwords │   │
   │  └─ Cloud Relay (DNA protocol passthrough)   │   │
   └─────────────────────────────────────────────┘   │
```

## How It Works

1. **Login** — Authenticates against `bizaccount.ibroadlink.com` using AES-128-CBC encrypted credentials (matching the mobile app's login flow)
2. **Discovery** — Retrieves device list, AES keys, and passwords from `bizihcv0.ibroadlink.com` via the bundled `kelvinator_dna.cloud` module
3. **Control** — Sends DNA protocol commands through the cloud relay via `libNetworkAPI.so` (when available)
4. **Status polling** — Queries device state on the configured poll interval

The bundled `kelvinator_dna` package contains a complete pure-Python implementation of the protocol stack — DNA packet framing, AES-128-ECB encryption, TFB serialization, and UDP device communication — available for future direct-LAN control.

## Troubleshooting

### Login fails during setup

- Verify you're using the **same credentials** as the Kelvinator mobile app
- If using a phone number, set the country code to `61` (AU) or `64` (NZ)
- Check the Home Assistant logs for specific error messages

### No devices discovered

- Log into the Kelvinator app on your phone and verify your AC units appear there
- The integration can only discover devices registered to your cloud account

### Commands don't work / devices show default state

- Device control currently requires `libNetworkAPI.so` (the BroadLink native library)
- Check logs for "DNA relay not available" — this means the native library wasn't found or isn't compatible with your architecture
- The `.so` file is architecture-specific; the version bundled may not match your platform

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

Licensed under the GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

[release-shield]: https://img.shields.io/github/v/release/kurobeats/Kelvinator-HASS-Addon.svg
[release]: https://github.com/kurobeats/Kelvinator-HASS-Addon/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/kurobeats/Kelvinator-HASS-Addon.svg
[commits]: https://github.com/kurobeats/Kelvinator-HASS-Addon/commits/main
[license-shield]: https://img.shields.io/github/license/kurobeats/Kelvinator-HASS-Addon.svg
[license]: LICENSE
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
