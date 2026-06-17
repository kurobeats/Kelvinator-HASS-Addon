# Changelog

## 2.0.0 (2026-06-17)

- Complete rewrite with bundled `kelvinator_dna` library (no unpublished pip dependencies)
- Cloud-first architecture: login and device discovery via BroadLink cloud API
- **Local UDP control** — sends DNA protocol commands directly to the AC over LAN (no cloud dependency for control)
- `DNALocalRelay` — pure-Python UDP device control with ARP table + subnet broadcast IP discovery
- `libNetworkAPI.so` included as optional cloud relay fallback (Android NDK binary — not loadable on standard Linux)
- Multi-source IP resolution: ARP table → subnet broadcast → global broadcast
- Fixed Family API device discovery (AES-encrypted JSON body, correct token formula)
- Climate entity with mode, temperature, fan speed, and swing control
- Switch entities: power, display, sleep, ECO per device
- Sensor entities: ambient temperature, error code per device
- Single-step config flow (username/password only)

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