# Kelvinator Home Comfort

[![GitHub Release][release-shield]][release]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![hacs][hacsbadge]][hacs]

Integration for controlling Kelvinator/Electrolux air conditioners in Home Assistant. Uses BroadLink cloud API for discovery and the DNA protocol for device control via cloud relay (no LAN access required).

## Features

- **Climate entity**: Full thermostat card with mode, temperature, fan speed, and swing
- **Switch entities**: Per-AC toggles for power, display, sleep, and ECO modes
- **Sensor entities**: Ambient temperature, error code
- **Cloud-only**: No LAN discovery or direct device access needed — everything goes through BroadLink's cloud relay
- **Single-step setup**: Just your Kelvinator app username and password
- **DNA native library**: Uses the reverse-engineered `libNetworkAPI.so` for protocol encoding and cloud relay

## Supported Devices

- Kelvinator split-system air conditioners registered with the Kelvinator/Electrolux mobile app
- BroadLink DNA protocol AC units (devtype 20379 / `0x4F9B`, pid `9b4f0000`)

## Requirements

| Requirement | Why |
|---|---|
| Kelvinator cloud account | Same email/phone and password as the mobile app |
| Home Assistant 2024.1+ | Integration framework |
| [kelvinator-dna](https://github.com/kurobeats/Kelvinator-DNA) ≥ 0.1.0 | Cloud API + DNA protocol library |
| `libNetworkAPI.so` | Native BroadLink library for device control (bundled) |

## Installation (HACS)

1. In Home Assistant, go to **HACS → Integrations**
2. Click the **⋮** menu → **Custom repositories**
3. Paste `https://github.com/kurobeats/Kelvinator-HASS-Addon` as the repository URL, select type **Integration**
4. Click **Add**, then find **Kelvinator Home Comfort** and click **Download**
5. Restart Home Assistant

## Installation (Manual)

1. Copy `custom_components/kelvinator/` into your HA config's `custom_components/` directory
2. Ensure `libNetworkAPI.so` is present inside the `kelvinator/` directory
3. Restart Home Assistant

## Configuration

Single-step setup via the Home Assistant UI:

1. Go to **Settings → Devices & Services** → **Add Integration**
2. Search for **Kelvinator Home Comfort** and select it
3. Enter your credentials:
   - **Username**: Email or phone number used in the Kelvinator app
   - **Password**: Kelvinator app password
   - **Country Code**: `61` for Australia, `64` for New Zealand (default: `61`)
   - **Poll Interval**: Refresh rate in seconds (default: `30`)
4. Click **Submit**

Devices are automatically discovered from your cloud account — no IP addresses needed.

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
│  ┌─────────────────────────────────────────┐     │
│  │ Kelvinator Integration                   │     │
│  │                                          │     │
│  │  ┌───────────────┐  ┌────────────────┐  │     │
│  │  │ config_flow.py│  │ coordinator.py │  │     │
│  │  │ (UI login)    │  │ (poll/refresh) │  │     │
│  │  └───────┬───────┘  └───────┬────────┘  │     │
│  │          │                  │            │     │
│  │  ┌───────▼──────────────────▼─────────┐ │     │
│  │  │ api.py                              │ │     │
│  │  │  ├─ KelvinatorCloudClient           │ │     │
│  │  │  │   └─ kelvinator_dna.cloud        │ │     │
│  │  │  │      → bizaccount/bizihcv0       │ │     │
│  │  │  ├─ KelvinatorACDevice              │ │     │
│  │  │  │   └─ send_command / update_state │ │     │
│  │  │  └─ DNACloudRelay                   │ │     │
│  │  │      └─ kelvinator_dna.so_bridge    │ │     │
│  │  │         → libNetworkAPI.so          │ │     │
│  │  └──────────────────┬──────────────────┘ │     │
│  │                     │                     │     │
│  │  ┌──────────────────▼──────────────────┐ │     │
│  │  │ climate.py / switch.py / sensor.py  │ │     │
│  │  └─────────────────────────────────────┘ │     │
│  └─────────────────────────────────────────┘ │     │
└──────────────────────┬───────────────────────┘     │
                       │ HTTPS (Cloud API)            │
                       ▼                              │
   ┌────────────────────────────────────┐             │
   │ BroadLink Cloud                     │             │
   │  ├─ bizaccount.ibroadlink.com      │             │
   │  │   → Account login               │             │
   │  ├─ bizihcv0.ibroadlink.com       │             │
   │  │   → Device discovery            │             │
   │  └─ Cloud Relay (DNA protocol)     │             │
   │      → Device control passthrough   │             │
   └──────────────┬─────────────────────┘             │
                  │                                    │
                  ▼                                    │
   ┌────────────────────────────────────┐             │
   │ Kelvinator AC Unit                  │             │
   │ (a0:43:b0:xx:xx:xx)                │             │
   └────────────────────────────────────┘             │
```

## How It Works

1. **Login** — Authenticates against `bizaccount.ibroadlink.com` using AES-encrypted credentials (matching the mobile app)
2. **Discovery** — Retrieves device list, AES keys, and passwords from `bizihcv0.ibroadlink.com` via `kelvinator_dna.cloud`
3. **Control** — Calls `libNetworkAPI.so` → `dnaControl()` JNI function with netmode=cloud. The native library handles DNA protocol encoding and cloud relay internally
4. **Status** — Polls device state via `deviceStatusOnServer` cloud endpoint

## DNA Native Library

Device control requires `libNetworkAPI.so` extracted from the Kelvinator/Electrolux APK:

```bash
# From APK
unzip kelvinator.apk -d apk_contents
cp apk_contents/lib/arm64-v8a/libNetworkAPI.so custom_components/kelvinator/
```

The `.so` file is architecture-specific. The integration ships with the x86_64 build — for ARM64 (Raspberry Pi / most HA installs), extract the `arm64-v8a` variant from the APK.

If the `.so` is missing, the integration will still:
- ✅ Login and discover devices
- ✅ Create entities with default state
- ❌ Not poll real-time state or send commands

Set `KELVINATOR_SO_PATH` environment variable to override the default path.

## Troubleshooting

### Login fails during setup

- Verify you're using the **same credentials** as the Kelvinator mobile app
- If using a phone number, include country code `61` (AU) or `64` (NZ)
- Check the Home Assistant logs for specific error messages

### No devices discovered

- Log into the Kelvinator app on your phone and verify your AC units appear there
- The integration can only discover devices registered to your cloud account

### Commands don't work / devices show default state

- Verify `libNetworkAPI.so` is in the correct location
- Check logs for "DNA relay not available" — this means the native library wasn't found
- For ARM64 devices (Raspberry Pi), use the `arm64-v8a` variant from the APK

## Change Log

Please see [CHANGELOG.md](CHANGELOG.md) for release information.

## License

This project is licensed under the GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

[release-shield]: https://img.shields.io/github/v/release/kurobeats/Kelvinator-HASS-Addon.svg
[release]: https://github.com/kurobeats/Kelvinator-HASS-Addon/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/kurobeats/Kelvinator-HASS-Addon.svg
[commits]: https://github.com/kurobeats/Kelvinator-HASS-Addon/commits/main
[license-shield]: https://img.shields.io/github/license/kurobeats/Kelvinator-HASS-Addon.svg
[license]: LICENSE
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
