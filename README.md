# Kelvinator Home Comfort

[![GitHub Release][release-shield]][release]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]][license]
[![hacs][hacsbadge]][hacs]

Integration for controlling Kelvinator air conditioners in Home Assistant via the BroadLink DNA protocol (LAN + cloud relay).

## Features

- **Climate entity**: Full thermostat card with mode, temperature, fan speed, and swing control
- **Auto-discovery**: Detects Kelvinator AC units on the LAN via UDP broadcast
- **LAN-first**: Direct UDP/TCP control when on the same network — no cloud required
- **Cloud relay**: Falls back to BroadLink cloud when remote
- **UI config flow**: Set up your credentials directly in the Home Assistant UI

## Supported Devices

- Kelvinator split-system air conditioners with built-in BroadLink Wi-Fi module
- Any BroadLink DNA-compatible AC unit (device types `0x4E2A`, `0x4E2B`, `0x4E2C`)

## Installation (HACS)

1. In Home Assistant, go to **HACS → Integrations**
2. Click the **⋮** menu → **Custom repositories**
3. Paste `https://github.com/ants/Kelvinator-HASS-Addon` as the repository URL, select type **Integration**
4. Click **Add**, then find **Kelvinator Home Comfort** and click **Download**
5. Restart Home Assistant

## Installation (Manual)

1. Using the tool of your choice, open the directory (folder) for your HA configuration (where you find `configuration.yaml`)
2. If you do not have a `custom_components` directory, create it
3. In `custom_components`, create a folder called `kelvinator`
4. Download all the files from the `custom_components/kelvinator/` directory in this repository and place them in the new folder you created
5. Restart Home Assistant

## Configuration

Configuration is done via the Home Assistant UI. You must have your Kelvinator AC unit connected to Wi-Fi via the Kelvinator mobile app first.

1. In Home Assistant, go to **Settings → Devices & Services**
2. Click **Add Integration** (blue button, bottom-right)
3. Search for **Kelvinator Home Comfort** and select it
4. Enter your Kelvinator app credentials:
   - **Username**: The email or phone number you use to log into the Kelvinator app
   - **Password**: Your Kelvinator app password
   - **Country Code**: `61` for Australia, `64` for New Zealand (default: `61`)
   - **Poll Interval**: How often to refresh device state in seconds (default: `30`)
5. Click **Submit** — the integration will validate your credentials and discover devices on your LAN
6. Your climate entities should appear as `climate.kelvinator_xxxx`

## Troubleshooting

### No devices discovered

- Make sure the AC unit is powered on and connected to Wi-Fi
- The AC and your Home Assistant machine must be on the **same subnet** (UDP discovery doesn't cross VLANs)
- Try restarting the AC unit

### Login failed

- Verify the username and password match what you use in the Kelvinator phone app
- If using a phone number, make sure the country code is correct (`61` = Australia, `64` = New Zealand)

### Device shows as unavailable

- The AC unit may have lost Wi-Fi or gone to sleep — the integration polls every 30 seconds and will recover automatically
- Check the Home Assistant logs for connection errors

## Architecture

```
┌──────────────────────────────────────────────┐
│  Home Assistant                               │
│                                               │
│  ┌─────────────────────────────────────────┐ │
│  │ Kelvinator Integration                   │ │
│  │                                          │ │
│  │  ┌───────────────┐  ┌────────────────┐  │ │
│  │  │ config_flow.py│  │ coordinator.py │  │ │
│  │  │ (UI login)    │  │ (poll every 30s)│  │ │
│  │  └───────┬───────┘  └───────┬────────┘  │ │
│  │          │                  │            │ │
│  │  ┌───────▼──────────────────▼─────────┐ │ │
│  │  │ api.py                              │ │ │
│  │  │  ├─ BroadLinkCloudClient (HTTPS)    │ │ │
│  │  │  ├─ KelvinatorACDevice (broadlink)  │ │ │
│  │  │  └─ discover_devices() (UDP)        │ │ │
│  │  └──────────────────┬──────────────────┘ │ │
│  │                     │                     │ │
│  │  ┌──────────────────▼──────────────────┐ │ │
│  │  │ climate.py                          │ │ │
│  │  │  • set_hvac_mode (cool/heat/dry/…)  │ │ │
│  │  │  • set_temperature                  │ │ │
│  │  │  • set_fan_mode / set_swing_mode    │ │ │
│  │  └─────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────┬───────────────────────┘
                       │ LAN (UDP/TCP)
               ┌───────▼───────┐
               │ Kelvinator AC │
               │ (BroadLink DNA)│
               └───────────────┘
```

## Requirements

- Home Assistant 2024.1 or later
- [python-broadlink](https://github.com/mjg59/python-broadlink) (`>=0.19.0`)
- [pycryptodome](https://pypi.org/project/pycryptodome/) (`>=3.20.0`)
- Kelvinator AC unit on the same LAN as Home Assistant

## Change Log

Please see [CHANGELOG.md](CHANGELOG.md) for release information.

## License

This project is licensed under the GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

[release-shield]: https://img.shields.io/github/v/release/ants/Kelvinator-HASS-Addon.svg
[release]: https://github.com/ants/Kelvinator-HASS-Addon/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/ants/Kelvinator-HASS-Addon.svg
[commits]: https://github.com/ants/Kelvinator-HASS-Addon/commits/main
[license-shield]: https://img.shields.io/github/license/ants/Kelvinator-HASS-Addon.svg
[license]: LICENSE
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs]: https://github.com/hacs/integration
3. Click **Kelvinator Home Comfort** → **Install**
4. Configure the options (see below)
5. Start the add-on

## Configuration

```yaml
username: "your@email.com"    # Kelvinator app login
password: "your_password"     # Kelvinator app password
country_code: "61"            # Your country code (61=AU, 64=NZ)
poll_interval: 30             # Status refresh interval (seconds)
debug: false                  # Enable debug logging
```

MQTT settings are auto-detected from the HA supervisor. You can override them:

```yaml
mqtt_host: "192.168.1.10"
mqtt_port: 1883
mqtt_username: "mqtt_user"
mqtt_password: "mqtt_pass"
```

## Supported Commands

| Command | Values |
|---------|--------|
| Power | ON / OFF |
| Mode | cool, heat, dry, fan_only, auto, eco |
| Temperature | 16–30 °C |
| Fan Speed | auto, low, medium, high, turbo, quiet |
| Swing | off, vertical, horizontal, both |
| Display | ON / OFF |
| Sleep | ON / OFF |
| ECO | ON / OFF |

## Requirements

- Home Assistant with MQTT broker (Mosquitto add-on recommended)
- Kelvinator AC unit with BroadLink WiFi module
- AC unit on same LAN as Home Assistant for best performance

## Troubleshooting

**No devices discovered**: Ensure your AC is on the same WiFi network as HA. Try power-cycling the AC.

**Connection errors**: The BroadLink module uses UDP broadcast for discovery. Ensure your network allows UDP on port 80.

**Wrong temperature range**: The add-on reads min/max from the device profile. If incorrect, check the device model number.

## License

GPL3