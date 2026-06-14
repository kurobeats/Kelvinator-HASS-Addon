#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

# Parse options from HA add-on config
USERNAME=$(jq -r '.username' "$CONFIG_PATH")
PASSWORD=$(jq -r '.password' "$CONFIG_PATH")
COUNTRY_CODE=$(jq -r '.country_code // "61"' "$CONFIG_PATH")
POLL_INTERVAL=$(jq -r '.poll_interval // 30' "$CONFIG_PATH")
MQTT_HOST=$(jq -r '.mqtt_host // empty' "$CONFIG_PATH")
MQTT_PORT=$(jq -r '.mqtt_port // 1883' "$CONFIG_PATH")
MQTT_USER=$(jq -r '.mqtt_username // empty' "$CONFIG_PATH")
MQTT_PASS=$(jq -r '.mqtt_password // empty' "$CONFIG_PATH")
MQTT_DISCOVERY_PREFIX=$(jq -r '.mqtt_discovery_prefix // "homeassistant"' "$CONFIG_PATH")
DEBUG=$(jq -r '.debug // false' "$CONFIG_PATH")

# If no MQTT host specified, use HA supervisor MQTT service
if [ -z "$MQTT_HOST" ]; then
    MQTT_HOST=$(bashio::services mqtt "host" 2>/dev/null || echo "core-mosquitto")
    MQTT_PORT=$(bashio::services mqtt "port" 2>/dev/null || echo "1883")
    MQTT_USER=$(bashio::services mqtt "username" 2>/dev/null || echo "")
    MQTT_PASS=$(bashio::services mqtt "password" 2>/dev/null || echo "")
fi

echo "=== Kelvinator Home Comfort Add-on ==="
echo "MQTT Broker: ${MQTT_HOST}:${MQTT_PORT}"
echo "Poll Interval: ${POLL_INTERVAL}s"
echo "Debug: ${DEBUG}"

# Run the bridge
exec python3 -u /app/bridge.py \
    --username "$USERNAME" \
    --password "$PASSWORD" \
    --country-code "$COUNTRY_CODE" \
    --poll-interval "$POLL_INTERVAL" \
    --mqtt-host "$MQTT_HOST" \
    --mqtt-port "$MQTT_PORT" \
    --mqtt-user "$MQTT_USER" \
    --mqtt-pass "$MQTT_PASS" \
    --mqtt-prefix "$MQTT_DISCOVERY_PREFIX" \
    $([ "$DEBUG" = "true" ] && echo "--debug")
