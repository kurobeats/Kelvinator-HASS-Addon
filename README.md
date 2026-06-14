# Kelvinator Home Comfort

[![GitHub Release][release-shield]][release]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![hacs][hacsbadge]][hacs]

Integration for controlling Kelvinator air conditioners in Home Assistant. Uses the Kelvinator cloud service (BroadLink) for device discovery and LAN for direct control.

## Features

- **Climate entity**: Full thermostat card with mode, temperature, fan speed, and vertical/horizontal swing
- **Switch entities**: Per-AC toggles for power, display, sleep, and ECO modes
- **Sensor entities**: Ambient temperature, error code, timer, and schedule status
- **Cloud device discovery**: Automatically finds all your registered air conditioners
- **LAN control**: Direct UDP/TCP commands to AC units on the same network
- **UI config flow**: Set up credentials and device IPs directly in the Home Assistant UI
- **Post-setup management**: Add or remove device IPs without restarting

## Supported Devices

- Kelvinator split-system air conditioners registered with the Kelvinator mobile app
- Any BroadLink DNA-compatible AC unit (device types `0x4E2A`, `0x4E2B`, `0x4E2C`)

## Requirements

| Requirement | Why |
|---|---|
| Kelvinator cloud account | Required for device discovery. Uses the same email/phone and password as the Kelvinator mobile app |
| Home Assistant 2024.1+ | Integration framework support |
| [python-broadlink](https://github.com/mjg59/python-broadlink) ≥ 0.19.0 | LAN device control |
| [pycryptodome](https://pypi.org/project/pycryptodome/) ≥ 3.20.0 | Cloud API encryption |
| AC units on same LAN as HA | Direct control requires TCP port 80 to the AC |

## Installation (HACS)

1. In Home Assistant, go to **HACS → Integrations**
2. Click the **⋮** menu → **Custom repositories**
3. Paste `https://github.com/kurobeats/Kelvinator-HASS-Addon` as the repository URL, select type **Integration**
4. Click **Add**, then find **Kelvinator Home Comfort** and click **Download**
5. Restart Home Assistant

## Installation (Manual)

1. Open your Home Assistant configuration directory (where `configuration.yaml` lives)
2. If you do not have a `custom_components` directory, create it
3. In `custom_components`, create a folder called `kelvinator`
4. Download all files from the `custom_components/kelvinator/` directory in this repository and place them there
5. Restart Home Assistant

## Configuration

Configuration is done via the Home Assistant UI in two steps.

### Step 1 — Account

1. Go to **Settings → Devices & Services** → **Add Integration**
2. Search for **Kelvinator Home Comfort** and select it
3. Enter your Kelvinator credentials:
   - **Username**: Email or phone number used in the Kelvinator app
   - **Password**: Kelvinator app password
   - **Country Code**: `61` for Australia, `64` for New Zealand
   - **Poll Interval**: Refresh rate in seconds (default: `30`)
   - **Enable LAN Discovery**: Leave ON to scan for devices on your network
4. Click **Next**

Your credentials are validated against the Kelvinator cloud service before proceeding.

### Step 2 — Device IPs

1. Enter your AC units' IP addresses, separated by commas:
   - Example: `192.168.1.50, 192.168.1.51, 192.168.1.52`
   - Leave blank to rely on LAN auto-discovery only
2. Each IP is probed to verify a BroadLink device responds
3. Click **Submit**

> **Note:** The cloud login provides device names and MAC addresses. LAN connectivity is needed for actual control. If your AC is not reachable on port 80, you'll see cloud names but the entities will show as unavailable.

### Managing Devices After Setup

1. Go to **Settings → Devices & Services → Kelvinator Home Comfort**
2. Click **⋮** → **Configure**
3. Edit IPs, poll interval, or enable/disable LAN discovery
4. Click **Submit** — the integration reloads automatically

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
| Sensor | `sensor.kelvinator_xxxx_timer` | Active timer |
| Sensor | `sensor.kelvinator_xxxx_schedule` | Schedule on/off state |
| Sensor | `sensor.kelvinator_xxxx_schedule_time` | Scheduled time |

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
│  │  │ (UI login)    │  │ (poll every 30s)│  │     │
│  │  └───────┬───────┘  └───────┬────────┘  │     │
│  │          │                  │            │     │
│  │  ┌───────▼──────────────────▼─────────┐ │     │
│  │  │ api.py                              │ │     │
│  │  │  ├─ BroadLinkCloudClient            │ │     │
│  │  │  │   └─ HTTPS → bizaccount/bizihcv0│ │     │
│  │  │  ├─ KelvinatorACDevice              │ │     │
│  │  │  │   └─ UDP/TCP → AC units          │ │     │
│  │  │  └─ discover_devices / probe_device │ │     │
│  │  └──────────────────┬──────────────────┘ │     │
│  │                     │                     │     │
│  │  ┌──────────────────▼──────────────────┐ │     │
│  │  │ climate.py / switch.py / sensor.py  │ │     │
│  │  │  • set_hvac_mode, set_temperature   │ │     │
│  │  │  • set_fan_mode, set_swing_mode     │ │     │
│  │  │  • toggle power/display/sleep/eco   │ │     │
│  │  │  • read ambient temp / error codes  │ │     │
│  │  └─────────────────────────────────────┘ │     │
│  └─────────────────────────────────────────┘ │     │
└──────────────────────┬───────────────────────┘     │
                       │                              │
          ┌────────────┼────────────┐                 │
          │ Cloud       │  LAN       │                 │
          ▼             ▼            ▼                 │
   ┌────────────┐ ┌────────────┐                     │
   │ BroadLink  │ │ Kelvinator │                     │
   │ Cloud API  │ │ AC Units   │                     │
   │ (HTTPS)    │ │ (UDP/TCP)  │                     │
   │ • login    │ │ port 80    │                     │
   │ • devices  │ │            │                     │
   └────────────┘ └────────────┘                     │
```

## Authentication Details

This integration communicates with the same BroadLink cloud infrastructure used by the Kelvinator mobile app. It was reverse-engineered from the Android APK (v3.8.2) and verified against live traffic captures. The login flow uses:

- AES-256-CBC encryption with zero-byte padding
- MD5-based request signing tokens
- SHA1(SHA256(password + salt)) password hashing
- `bizaccount.ibroadlink.com` for authentication
- `bizihcv0.ibroadlink.com` for device family management

## Troubleshooting

### Login fails during setup

- Verify you're using the **same credentials** as the Kelvinator mobile app
- If using a phone number, include country code `61` (AU) or `64` (NZ)
- Check the Home Assistant logs for specific error messages

### No devices discovered from cloud

- Log into the Kelvinator app on your phone and verify your AC units appear there
- The integration can only discover devices registered to your cloud account

### Devices appear but show as unavailable

- The AC must be on the **same subnet** as Home Assistant for LAN control
- TCP port 80 must be reachable on the AC unit
- Try specifying the AC's IP address directly in the **Device IPs** config field
- Assign static DHCP leases to your AC units to prevent IP changes

### "No BroadLink device at X.X.X.X"

- Port 80 is closed on the AC — the integration can't reach it over LAN
- The AC may have gone to sleep or lost Wi-Fi
- Power-cycle the AC and try again

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
[hacs]: https://github.com/hacs/integration
