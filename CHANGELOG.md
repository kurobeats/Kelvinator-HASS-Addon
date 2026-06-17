# Changelog

## 2.0.0 (2026-06-17)

- Complete rewrite with bundled `kelvinator_dna` library (no unpublished pip dependencies)
- Cloud-first architecture: login, device discovery, and control via BroadLink cloud API
- Climate entity with mode, temperature, fan speed, and swing control
- Switch entities: power, display, sleep, ECO per device
- Sensor entities: ambient temperature, error code per device
- Single-step config flow (username/password only)
- DNA protocol integration via `libNetworkAPI.so` cloud relay
- Pure-Python protocol implementation included for future direct-LAN control

## 1.0.0 (2026-06-14)

- Initial release
- BroadLink DNA protocol integration via python-broadlink
- MQTT auto-discovery for Home Assistant
- Climate entity with mode, temperature, fan, swing control
- Ambient temperature sensor
- Error code sensor
- Switch entities for display, sleep, ECO, anion, mould proof, self clean, mosquito
- LAN-first device control with cloud relay fallback
- BroadLink cloud API client for account management