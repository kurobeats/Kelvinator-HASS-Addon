# Kelvinator Home Comfort — Home Assistant Add-on

Control your Kelvinator air conditioners through Home Assistant using the BroadLink DNA protocol.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Home Assistant                       │
│  ┌─────────────┐  MQTT   ┌────────────────────────┐ │
│  │ MQTT Broker │◄───────►│ Kelvinator Add-on       │ │
│  │ (Mosquitto) │         │                         │ │
│  └─────────────┘         │ ┌─────────────────────┐ │ │
│                          │ │ cloud_client.py     │ │ │
│                          │ │ (BroadLink Cloud)   │ │ │
│                          │ └─────────┬───────────┘ │ │
│                          │           │ HTTPS        │ │
│                          │ ┌─────────▼───────────┐ │ │
│                          │ │ device_client.py    │ │ │
│                          │ │ (python-broadlink)  │ │ │
│                          │ └─────────┬───────────┘ │ │
│                          │           │ UDP/TCP      │ │
│                          │ ┌─────────▼───────────┐ │ │
│                          │ │ bridge.py           │ │ │
│                          │ │ (MQTT ↔ Device)     │ │ │
│                          │ └─────────────────────┘ │ │
│                          └────────────────────────┘ │
└──────────────────────────────────────────────────────┘
           │                          │
           ▼                          ▼
    ┌─────────────┐          ┌──────────────┐
    │ BroadLink   │          │ Kelvinator   │
    │ Cloud API   │          │ AC Unit      │
    │ (optional)  │          │ (LAN)        │
    └─────────────┘          └──────────────┘
```

## Features

- **Auto-discovery**: Devices appear automatically in HA via MQTT discovery
- **Climate entity**: Full thermostat card with mode, temp, fan, swing
- **Sensors**: Ambient temperature, error codes
- **Switches**: Display, Sleep, ECO, Anion, Mould Proof, Self Clean, Mosquito
- **LAN-first**: Direct UDP/TCP control when on same network
- **Cloud relay**: Falls back to BroadLink cloud when remote

## Installation

1. Copy this folder to your Home Assistant `addons/` directory
2. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Local add-ons**
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