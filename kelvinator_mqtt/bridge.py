#!/usr/bin/env python3
"""
Kelvinator Home Comfort → Home Assistant MQTT Bridge.

Architecture:
  - CloudClient: BroadLink cloud API for login & device list retrieval
  - KelvinatorACDevice: python-broadlink for LAN/cloud device control
  - MQTT: HA auto-discovery + state/command topics

Flow:
  1. Login to BroadLink cloud
  2. Get device list from cloud
  3. For each device, discover LAN address via broadlink
  4. Register HA MQTT discovery config
  5. Loop: poll device state → publish MQTT state
  6. Listen for MQTT commands → send to device
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

from cloud_client import BroadLinkCloudClient, _DEFAULT_LICENSE_ID
from device_client import (
    AcDeviceState,
    AcMode,
    FanSpeed,
    KelvinatorACDevice,
    discover_devices,
)

_LOGGER = logging.getLogger("kelvinator_bridge")

# ---------------------------------------------------------------------------
# MQTT topic helpers
# ---------------------------------------------------------------------------


def _discovery_topic(prefix: str, component: str, device_id: str) -> str:
    return f"{prefix}/{component}/{device_id}/config"


def _state_topic(device_id: str) -> str:
    return f"kelvinator/{device_id}/state"


def _command_topic(device_id: str) -> str:
    return f"kelvinator/{device_id}/command"


# ---------------------------------------------------------------------------
# HA MQTT Discovery payload builders
# ---------------------------------------------------------------------------


def _device_info(dev: KelvinatorACDevice) -> dict:
    return {
        "identifiers": [f"kelvinator_{dev.mac}"],
        "name": dev.name,
        "manufacturer": "Kelvinator",
        "model": dev.state.model_number or "Unknown",
        "sw_version": "BroadLink DNA",
        "via_device": "kelvinator_bridge",
    }


def _climate_discovery(dev: KelvinatorACDevice, prefix: str) -> dict:
    device_id = dev.mac.replace(":", "_").lower()
    return {
        "name": dev.name,
        "unique_id": f"kelvinator_ac_{device_id}",
        "device": _device_info(dev),
        "availability_topic": f"kelvinator/{device_id}/availability",
        "state_topic": _state_topic(device_id),
        "command_topic": _command_topic(device_id),
        "temperature_command_topic": f"kelvinator/{device_id}/temp/set",
        "mode_command_topic": f"kelvinator/{device_id}/mode/set",
        "fan_mode_command_topic": f"kelvinator/{device_id}/fan/set",
        "swing_mode_command_topic": f"kelvinator/{device_id}/swing/set",
        "temperature_state_topic": _state_topic(device_id),
        "temperature_state_template": "{{ value_json.target_temp }}",
        "current_temperature_topic": _state_topic(device_id),
        "current_temperature_template": "{{ value_json.ambient_temp }}",
        "mode_state_topic": _state_topic(device_id),
        "mode_state_template": "{{ value_json.mode }}",
        "fan_mode_state_topic": _state_topic(device_id),
        "fan_mode_state_template": "{{ value_json.fan_speed }}",
        "swing_mode_state_topic": _state_topic(device_id),
        "swing_mode_state_template": "{{ value_json.swing }}",
        "modes": ["off", "cool", "heat", "dry", "fan_only", "auto", "eco"],
        "fan_modes": ["auto", "low", "medium", "high", "turbo", "quiet"],
        "swing_modes": ["off", "vertical", "horizontal", "both"],
        "min_temp": dev.state.temp_min_c,
        "max_temp": dev.state.temp_max_c,
        "temp_step": 1,
        "temperature_unit": "C",
        "payload_on": "ON",
        "payload_off": "OFF",
        "precision": 1.0,
        "qos": 1,
        "retain": True,
    }


def _sensor_discoveries(dev: KelvinatorACDevice, prefix: str) -> list[dict]:
    """Additional sensor entities for ambient temp, error code, etc."""
    device_id = dev.mac.replace(":", "_").lower()
    base_topic = _state_topic(device_id)
    di = _device_info(dev)

    sensors = []

    # Ambient temperature
    sensors.append({
        "name": f"{dev.name} Ambient Temp",
        "unique_id": f"kelvinator_ac_{device_id}_ambient_temp",
        "device": di,
        "state_topic": base_topic,
        "value_template": "{{ value_json.ambient_temp }}",
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "qos": 1,
    })

    # Error code
    sensors.append({
        "name": f"{dev.name} Error Code",
        "unique_id": f"kelvinator_ac_{device_id}_error",
        "device": di,
        "state_topic": base_topic,
        "value_template": "{{ value_json.error_code }}",
        "icon": "mdi:alert-circle",
        "qos": 1,
    })

    return sensors


def _switch_discoveries(dev: KelvinatorACDevice, prefix: str) -> list[dict]:
    """Additional switch entities for display, sleep, ECO, etc."""
    device_id = dev.mac.replace(":", "_").lower()
    cmd_topic = _command_topic(device_id)
    state_topic = _state_topic(device_id)
    di = _device_info(dev)

    switches = []
    for name, uid_suffix, state_key in [
        ("Display", "display", "display_on"),
        ("Sleep", "sleep", "sleep"),
        ("ECO", "eco", "eco"),
        ("Anion", "anion", "anion"),
        ("Mould Proof", "mould_proof", "mould_proof"),
        ("Self Clean", "self_clean", "self_clean"),
        ("Mosquito Repellent", "mosquito", "mosquito"),
    ]:
        switches.append({
            "name": f"{dev.name} {name}",
            "unique_id": f"kelvinator_ac_{device_id}_{uid_suffix}",
            "device": di,
            "state_topic": state_topic,
            "state_value_template": "{{ 'ON' if value_json." + state_key + " else 'OFF' }}",
            "command_topic": cmd_topic,
            "payload_on": json.dumps({"switch": state_key, "value": True}),
            "payload_off": json.dumps({"switch": state_key, "value": False}),
            "qos": 1,
        })

    return switches


# ---------------------------------------------------------------------------
# MQTT Bridge
# ---------------------------------------------------------------------------


class KelvinatorBridge:
    """Main bridge: login → discover → MQTT → poll loop."""

    def __init__(
        self,
        username: str,
        password: str,
        mqtt_host: str,
        mqtt_port: int = 1883,
        mqtt_user: str = "",
        mqtt_pass: str = "",
        mqtt_prefix: str = "homeassistant",
        poll_interval: int = 30,
        country_code: str = "61",
        debug: bool = False,
    ) -> None:
        self._cloud = BroadLinkCloudClient()
        self._devices: dict[str, KelvinatorACDevice] = {}
        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port
        self._mqtt_user = mqtt_user
        self._mqtt_pass = mqtt_pass
        self._mqtt_prefix = mqtt_prefix
        self._poll_interval = poll_interval
        self._debug = debug
        self._running = False

        self._mqtt = mqtt.Client(
            client_id=f"kelvinator_bridge_{int(time.time())}",
            protocol=mqtt.MQTTv5,
        )
        self._mqtt.on_connect = self._on_mqtt_connect
        self._mqtt.on_message = self._on_mqtt_message
        self._mqtt.on_disconnect = self._on_mqtt_disconnect

        if mqtt_user:
            self._mqtt.username_pw_set(mqtt_user, mqtt_pass)

        # Will message — mark all devices unavailable if bridge goes down
        self._mqtt.will_set(
            "kelvinator/bridge/status",
            payload="offline",
            qos=1,
            retain=True,
        )

        # Command handlers
        self._cmd_handlers = {
            "climate": self._handle_climate_command,
            "temp": self._handle_temp_command,
            "mode": self._handle_mode_command,
            "fan": self._handle_fan_command,
            "swing": self._handle_swing_command,
            "switch": self._handle_switch_command,
        }

    # -------------------------------------------------- MQTT Callbacks

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, props):
        _LOGGER.info("MQTT connected [rc=%d]", reason_code)
        self._mqtt.publish(
            "kelvinator/bridge/status", "online", qos=1, retain=True
        )
        # Subscribe to all device command topics
        self._mqtt.subscribe("kelvinator/+/command", qos=1)
        self._mqtt.subscribe("kelvinator/+/temp/set", qos=1)
        self._mqtt.subscribe("kelvinator/+/mode/set", qos=1)
        self._mqtt.subscribe("kelvinator/+/fan/set", qos=1)
        self._mqtt.subscribe("kelvinator/+/swing/set", qos=1)

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, props):
        _LOGGER.warning("MQTT disconnected [rc=%d]", reason_code)

    def _on_mqtt_message(self, client, userdata, msg):
        """Route MQTT command to appropriate handler."""
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        _LOGGER.debug("MQTT ← %s: %s", topic, payload)

        parts = topic.split("/")
        if len(parts) < 3:
            return

        device_id = parts[1]  # kelvinator/{device_id}/...
        subtopic = parts[2] if len(parts) > 2 else ""

        # Find the device by mac (with underscore form)
        target_dev = None
        for mac, dev in self._devices.items():
            if mac.replace(":", "_").lower() == device_id:
                target_dev = dev
                break

        if target_dev is None:
            _LOGGER.warning("Unknown device: %s", device_id)
            return

        asyncio.run_coroutine_threadsafe(
            self._dispatch_command(target_dev, subtopic, payload),
            self._loop,
        )

    # -------------------------------------------------- Command handling

    async def _dispatch_command(
        self, dev: KelvinatorACDevice, subtopic: str, payload: str
    ) -> None:
        """Dispatch an MQTT command to the right handler."""
        try:
            if subtopic == "command":
                await self._handle_command(dev, payload)
            elif subtopic == "temp" or subtopic == "set":
                # temp/set
                try:
                    tmp = int(float(payload))
                    await dev.set_temperature(tmp)
                except ValueError:
                    _LOGGER.warning("Invalid temp: %s", payload)
            elif subtopic == "mode":
                await self._handle_mode(dev, payload)
            elif subtopic == "fan":
                await self._handle_fan(dev, payload)
            elif subtopic == "swing":
                await self._handle_swing(dev, payload)
        except Exception as exc:
            _LOGGER.error("Command error: %s", exc)

    async def _handle_command(self, dev: KelvinatorACDevice, payload: str) -> None:
        """Handle a climate command (OFF, COOL, etc. from HA)."""
        p = payload.strip().upper()

        if p == "OFF":
            await dev.set_power(False)
        elif p == "ON":
            await dev.set_power(True)
        else:
            # Try as mode name
            mode_map = {
                "COOL": AcMode.COOL, "HEAT": AcMode.HEAT,
                "DRY": AcMode.DRY, "FAN_ONLY": AcMode.FAN_ONLY,
                "AUTO": AcMode.AUTO, "ECO": AcMode.ECO,
            }
            if p in mode_map:
                await dev.set_power(True)
                await dev.set_mode(mode_map[p])
            else:
                # Try as JSON switch command
                try:
                    data = json.loads(p)
                    await self._handle_switch_json(dev, data)
                except json.JSONDecodeError:
                    _LOGGER.warning("Unknown command: %s", p)

    async def _handle_mode(self, dev: KelvinatorACDevice, payload: str) -> None:
        p = payload.strip().upper()
        mode_map = {
            "COOL": AcMode.COOL, "HEAT": AcMode.HEAT,
            "DRY": AcMode.DRY, "FAN_ONLY": AcMode.FAN_ONLY,
            "AUTO": AcMode.AUTO, "ECO": AcMode.ECO,
        }
        if p in mode_map:
            await dev.set_mode(mode_map[p])

    async def _handle_fan(self, dev: KelvinatorACDevice, payload: str) -> None:
        p = payload.strip().upper()
        fan_map = {
            "AUTO": FanSpeed.AUTO, "LOW": FanSpeed.LOW,
            "MEDIUM": FanSpeed.MEDIUM, "HIGH": FanSpeed.HIGH,
            "TURBO": FanSpeed.TURBO, "QUIET": FanSpeed.QUIET,
        }
        if p in fan_map:
            await dev.set_fan_speed(fan_map[p])

    async def _handle_swing(self, dev: KelvinatorACDevice, payload: str) -> None:
        p = payload.strip().upper()
        if p == "VERTICAL":
            await dev.set_swing_v(True)
        elif p == "HORIZONTAL":
            await dev.set_swing_h(True)
        elif p == "BOTH":
            await dev.set_swing_v(True)
            await dev.set_swing_h(True)
        elif p == "OFF":
            await dev.set_swing_v(False)
            await dev.set_swing_h(False)

    async def _handle_switch_json(
        self, dev: KelvinatorACDevice, data: dict
    ) -> None:
        """Handle {switch: name, value: bool} commands."""
        name = data.get("switch", "")
        value = bool(data.get("value", False))
        _LOGGER.debug("Switch: %s = %s", name, value)

    # -------------------------------------------------- Main loop

    async def run(self) -> None:
        """Main entry point: login, discover, register, poll."""
        self._running = True

        # 1. Connect to MQTT
        _LOGGER.info("Connecting to MQTT at %s:%d", self._mqtt_host, self._mqtt_port)
        self._mqtt.connect(self._mqtt_host, self._mqtt_port, keepalive=60)
        self._mqtt.loop_start()

        # Give MQTT a moment
        await asyncio.sleep(1)

        # 2. Discover devices on LAN
        _LOGGER.info("Discovering BroadLink devices on LAN...")
        discovered = await discover_devices(timeout=5)

        if not discovered:
            _LOGGER.warning(
                "No BroadLink devices discovered on LAN. "
                "Make sure devices are connected to the same network."
            )
            # Still enter poll loop — devices might appear later
        else:
            for dev in discovered:
                self._devices[dev.mac] = dev
                if await dev.connect():
                    await dev.update_state()
                    _LOGGER.info(
                        "Device %s [%s]: power=%s temp=%d°C",
                        dev.name, dev.mac,
                        dev.state.power, dev.state.target_temp,
                    )

        # 3. Register HA MQTT discovery
        self._register_discovery()

        # 4. Poll loop
        _LOGGER.info("Starting poll loop (interval=%ds)", self._poll_interval)
        while self._running:
            await self._poll_devices()
            await asyncio.sleep(self._poll_interval)

    def _register_discovery(self) -> None:
        """Publish MQTT discovery configs for all known devices."""
        prefix = self._mqtt_prefix

        for dev in self._devices.values():
            device_id = dev.mac.replace(":", "_").lower()

            # Climate entity
            climate_config = _climate_discovery(dev, prefix)
            self._mqtt.publish(
                _discovery_topic(prefix, "climate", f"kelvinator_ac_{device_id}"),
                json.dumps(climate_config),
                qos=1,
                retain=True,
            )
            _LOGGER.info("Registered climate: %s", dev.name)

            # Additional sensors
            for sensor_config in _sensor_discoveries(dev, prefix):
                uid = sensor_config["unique_id"]
                self._mqtt.publish(
                    _discovery_topic(prefix, "sensor", uid),
                    json.dumps(sensor_config),
                    qos=1,
                    retain=True,
                )

            # Additional switches
            for switch_config in _switch_discoveries(dev, prefix):
                uid = switch_config["unique_id"]
                self._mqtt.publish(
                    _discovery_topic(prefix, "switch", uid),
                    json.dumps(switch_config),
                    qos=1,
                    retain=True,
                )

    async def _poll_devices(self) -> None:
        """Poll all devices and publish state to MQTT."""
        for dev in self._devices.values():
            device_id = dev.mac.replace(":", "_").lower()
            av_topic = f"kelvinator/{device_id}/availability"

            ok = await dev.update_state()

            if ok:
                self._mqtt.publish(av_topic, "online", qos=1, retain=True)
                self._publish_state(dev)
            else:
                self._mqtt.publish(av_topic, "offline", qos=1, retain=True)
                _LOGGER.warning("Device %s unreachable", dev.name)

    def _publish_state(self, dev: KelvinatorACDevice) -> None:
        """Convert device state to MQTT JSON and publish."""
        s = dev.state
        device_id = dev.mac.replace(":", "_").lower()

        # Map AcMode to HA mode string
        mode_map = {
            AcMode.COOL: "cool", AcMode.HEAT: "heat",
            AcMode.DRY: "dry", AcMode.FAN_ONLY: "fan_only",
            AcMode.AUTO: "auto", AcMode.ECO: "eco",
            AcMode.EIGHT_HEAT: "heat", AcMode.TWELVE_HEAT: "heat",
        }

        fan_map = {
            FanSpeed.AUTO: "auto", FanSpeed.LOW: "low",
            FanSpeed.MEDIUM: "medium", FanSpeed.HIGH: "high",
            FanSpeed.TURBO: "turbo", FanSpeed.QUIET: "quiet",
            FanSpeed.LOW_MED: "low", FanSpeed.MED_HIGH: "medium",
        }

        # Swing state
        if s.swing_vertical and s.swing_horizontal:
            swing = "both"
        elif s.swing_vertical:
            swing = "vertical"
        elif s.swing_horizontal:
            swing = "horizontal"
        else:
            swing = "off"

        payload = {
            "power": "ON" if s.power else "OFF",
            "mode": mode_map.get(s.mode, "off") if s.power else "off",
            "target_temp": s.target_temp,
            "ambient_temp": s.ambient_temp,
            "fan_speed": fan_map.get(s.fan_speed, "auto"),
            "swing": swing,
            "display_on": s.display_on,
            "sleep": s.sleep,
            "eco": s.eco,
            "anion": s.anion,
            "mould_proof": s.mould_proof,
            "self_clean": s.self_clean,
            "mosquito": s.mosquito,
            "error_code": s.error_code,
            "temp_min": s.temp_min_c,
            "temp_max": s.temp_max_c,
        }

        topic = _state_topic(device_id)
        self._mqtt.publish(topic, json.dumps(payload), qos=1, retain=True)
        _LOGGER.debug("MQTT → %s: %s", topic, json.dumps(payload))

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        _LOGGER.info("Shutting down...")
        self._running = False

        # Mark all devices unavailable
        for mac in self._devices:
            device_id = mac.replace(":", "_").lower()
            self._mqtt.publish(
                f"kelvinator/{device_id}/availability",
                "offline", qos=1, retain=True,
            )

        self._mqtt.publish(
            "kelvinator/bridge/status", "offline", qos=1, retain=True
        )
        self._mqtt.loop_stop()
        self._mqtt.disconnect()
        self._cloud.close()
        _LOGGER.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Kelvinator ↔ HA MQTT Bridge")
    parser.add_argument("--username", required=True, help="Kelvinator app username")
    parser.add_argument("--password", required=True, help="Kelvinator app password")
    parser.add_argument("--country-code", default="61", help="Country code")
    parser.add_argument("--poll-interval", type=int, default=30)
    parser.add_argument("--mqtt-host", required=True)
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-user", default="")
    parser.add_argument("--mqtt-pass", default="")
    parser.add_argument("--mqtt-prefix", default="homeassistant")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Suppress noisy libraries
    logging.getLogger("paho").setLevel(logging.WARNING)
    logging.getLogger("broadlink").setLevel(logging.WARNING)

    bridge = KelvinatorBridge(
        username=args.username,
        password=args.password,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_user=args.mqtt_user,
        mqtt_pass=args.mqtt_pass,
        mqtt_prefix=args.mqtt_prefix,
        poll_interval=args.poll_interval,
        country_code=args.country_code,
        debug=args.debug,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bridge._loop = loop

    def sig_handler():
        asyncio.ensure_future(bridge.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, sig_handler)

    try:
        loop.run_until_complete(bridge.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(bridge.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
