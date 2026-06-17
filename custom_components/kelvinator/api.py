"""
Kelvinator Home Comfort — API layer.

Uses the bundled kelvinator_dna package for:
  - Cloud device discovery (HTTPS REST API via kelvinator_dna.cloud)
  - DNA protocol control (UDP or cloud relay via libNetworkAPI.so)
"""

from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .const import DEFAULT_LICENSE_ID, COMPANY_ID, AES_IV, PASSWORD_SALT, TIMESTAMP_SALT, TOKEN_SALT

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to locate libNetworkAPI.so for cloud relay
# ---------------------------------------------------------------------------

_SO_DIR = os.path.dirname(os.path.abspath(__file__))
_SO_PATH = os.environ.get(
    "KELVINATOR_SO_PATH",
    os.path.join(_SO_DIR, "libNetworkAPI.so"),
)
_SO_AVAILABLE = os.path.exists(_SO_PATH)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CloudDeviceInfo:
    """Device credentials retrieved from the BroadLink cloud."""
    did: str
    mac: str
    name: str = "Kelvinator AC"
    pid: str = ""
    password: int = 0
    aes_key: str = ""
    devtype: int = 20379
    terminal_id: int = 1
    sub_device_num: int = 0


@dataclass
class AcDeviceState:
    """Full state of a Kelvinator AC unit, normalized for HA."""
    power: bool = False
    mode: int = 0       # 0=cool, 1=heat, 2=auto, 3=fan, 4=dry
    target_temp: int = 24
    fan: int = 0        # 0=auto, 1=low, 2=med, 3=high
    swing: int = 0      # 0=off, 1=vert, 2=horiz, 3=both
    sleep: bool = False
    eco: bool = False
    display_on: bool = True
    temp_unit_celsius: bool = True
    ambient_temp: float = 0.0
    error_code: int = 0
    temp_min_c: int = 16
    temp_max_c: int = 30
    model_number: str = ""
    serial_number: str = ""


# ---------------------------------------------------------------------------
# Synchronous cloud helpers (run in executor threads)
# ---------------------------------------------------------------------------


def _cloud_login_sync(
    license_id: str, username: str, password: str,
) -> tuple[str, str]:
    """Blocking cloud login using kelvinator_dna.cloud."""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    ts = str(int(time.time()))
    pw_sha256 = hashlib.sha256((password + PASSWORD_SALT).encode()).hexdigest().lower()
    pw_hash = hashlib.sha1(pw_sha256.encode()).hexdigest().lower()

    body = _json.dumps({
        "phone" if username.isdigit() else "email": username,
        "password": pw_hash,
        "companyid": COMPANY_ID,
    }, separators=(",", ":"))

    aes_key = bytes.fromhex(hashlib.md5(
        (ts + TIMESTAMP_SALT).encode()
    ).hexdigest().lower())
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=AES_IV)
    encrypted = cipher.encrypt(pad(body.encode(), AES.block_size))
    token = hashlib.md5(body.encode() + TOKEN_SALT.encode()).hexdigest().lower()

    import urllib.request
    import ssl
    ctx = ssl.create_default_context()

    url = f"https://{license_id}bizaccount.ibroadlink.com/account/login"
    req = urllib.request.Request(
        url, data=encrypted,
        headers={
            "Content-Type": "application/x-java-serialized-object",
            "system": "android", "appPlatform": "android",
            "language": "en-au", "timestamp": ts, "token": token,
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = _json.loads(resp.read().decode())

    if data.get("error") != 0:
        raise RuntimeError(f"Login failed: {data.get('msg', 'Unknown error')}")
    return data["userid"], data["loginsession"]


def _cloud_discover_sync(
    license_id: str, user_id: str, login_session: str, language: str,
) -> list[CloudDeviceInfo]:
    """Blocking cloud device discovery using kelvinator_dna.cloud."""
    from .kelvinator_dna.cloud import KelvinatorCloud

    cloud = KelvinatorCloud(
        license_id=license_id,
        user_id=user_id,
        login_session=login_session,
        language=language,
    )
    cloud.authenticate()
    raw_devices = cloud.discover_devices()

    devices = []
    for d in raw_devices:
        devices.append(CloudDeviceInfo(
            did=d.did,
            mac=d.mac,
            name=d.name,
            pid=d.pid,
            password=d.password,
            aes_key=d.aes_key,
            devtype=getattr(d, "devtype", 20379),
            terminal_id=getattr(d, "terminal_id", 1),
            sub_device_num=getattr(d, "sub_device_num", 0),
        ))
    return devices


# ---------------------------------------------------------------------------
# Cloud API client
# ---------------------------------------------------------------------------


class KelvinatorCloudClient:
    """Async wrapper for BroadLink cloud discovery."""

    def __init__(
        self,
        license_id: str = DEFAULT_LICENSE_ID,
        country_code: str = "61",
        timeout: int = 15,
    ) -> None:
        self._license_id = license_id
        self._language = "en"
        self._timeout = timeout
        self._userid: Optional[str] = None
        self._loginsession: Optional[str] = None

    async def login(self, username: str, password: str) -> None:
        """Log in to BroadLink cloud."""
        user_id, login_session = await asyncio.to_thread(
            _cloud_login_sync, self._license_id, username, password,
        )
        self._userid = user_id
        self._loginsession = login_session
        _LOGGER.info("Cloud login OK (uid=%s)", user_id)

    async def discover_devices(self) -> list[CloudDeviceInfo]:
        """Discover all AC devices linked to this account."""
        if not self._userid or not self._loginsession:
            _LOGGER.error("Not authenticated")
            return []
        return await asyncio.to_thread(
            _cloud_discover_sync,
            self._license_id,
            self._userid,
            self._loginsession,
            self._language,
        )

    @property
    def userid(self) -> Optional[str]:
        return self._userid


# ---------------------------------------------------------------------------
# DNA cloud relay
# ---------------------------------------------------------------------------


class DNACloudRelay:
    """Cloud relay control using libNetworkAPI.so via kelvinator_dna.so_bridge."""

    def __init__(self, so_path: str = _SO_PATH) -> None:
        if not _SO_AVAILABLE:
            raise RuntimeError(f"libNetworkAPI.so not found at {so_path}")
        from .kelvinator_dna.so_bridge import NetworkAPI
        self._api = NetworkAPI(so_path)
        self._api.sdk_init("{}")

    def send_command(
        self,
        did: str, mac: str, aes_key: str, password: int, command_json: str,
    ) -> dict:
        result = self._api.dna_control(did, mac, aes_key, str(password), command_json)
        return _json.loads(result)

    def get_status(self, config_json: str) -> dict:
        result = self._api.device_status_on_server(config_json)
        return _json.loads(result)


class DNALocalRelay:
    """
    Local UDP control using the pure-Python DNA protocol implementation.

    Falls back to LAN discovery when the native libNetworkAPI.so is unavailable.
    Each device gets a persistent UDP socket and an asyncio lock for thread safety.
    """

    def __init__(self) -> None:
        self._devices: dict[str, "KelvinatorDevice"] = {}
        self._lock = threading.Lock()
        self._ip_cache: dict[str, str] = {}  # mac_lower → ip

    # ------------------------------------------------------------------
    # Public interface (matches DNACloudRelay)
    # ------------------------------------------------------------------

    def send_command(
        self,
        did: str, mac: str, aes_key: str, password: int, command_json: str,
    ) -> dict:
        """Send a control command to the device via local UDP."""
        try:
            dev = self._get_device(did, mac, aes_key, password)
            cmd = _json.loads(command_json)
            params: dict = cmd.get("params", {})

            if "power" in params:
                dev.set_power(bool(params["power"]))
            if "mode" in params:
                dev.set_mode(int(params["mode"]))
            if "temp" in params:
                dev.set_temperature(int(params["temp"]))
            if "fan" in params:
                dev.set_fan_speed(int(params["fan"]))
            if "vdir" in params or "hdir" in params:
                v = int(params.get("vdir", 0))
                h = int(params.get("hdir", 0))
                dev.set_swing((1 if v else 0) | (2 if h else 0))
            if "sleep" in params:
                dev.set_sleep(bool(params["sleep"]))

            dev.send_control()
            return {"status": 0}
        except Exception as exc:
            _LOGGER.error("Local command failed for %s: %s", mac, exc)
            return {"status": -1, "message": str(exc)}

    def get_status(self, config_json: str) -> dict:
        """Query device state via local UDP."""
        try:
            config = _json.loads(config_json)
            did = config["did"]
            mac = config["mac"]
            aes_key = config["aes_key"]
            password = int(config["password"])

            dev = self._get_device(did, mac, aes_key, password)
            status = dev.get_status()

            return {
                "status": 0,
                "data": {
                    "ac_pwr": 1 if status.power else 0,
                    "ac_mode": status.mode,
                    "temp": status.temp,
                    "ac_mark": status.fan,
                    "envtemp": status.room_temp or 0,
                    "ac_errcode": status.error_code,
                    "ac_vdir": status.swing,
                    "ac_slp": 1 if status.sleep else 0,
                },
            }
        except Exception as exc:
            _LOGGER.error("Local status failed: %s", exc)
            return {"status": -1, "message": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_device(
        self, did: str, mac: str, aes_key: str, password: int,
    ) -> "KelvinatorDevice":
        """Get or create a local KelvinatorDevice for the given MAC/DID."""
        dev = self._devices.get(did)
        if dev is not None:
            return dev
        with self._lock:
            if did in self._devices:
                return self._devices[did]
            ip = self._discover_ip(mac)
            if not ip:
                raise RuntimeError(
                    f"Cannot find LAN IP for {mac}. "
                    f"Make sure the AC is on the same network as Home Assistant."
                )
            from .kelvinator_dna.device import KelvinatorDevice
            dev = KelvinatorDevice(
                ip=ip, did=did, mac=mac, aes_key=aes_key, password=password,
            )
            dev.connect()
            dev.authenticate()
            self._devices[did] = dev
            _LOGGER.info("Local device connected: %s @ %s", mac, ip)
        return self._devices[did]

    def _discover_ip(self, mac: str) -> Optional[str]:
        """Find the LAN IP for a given MAC address via UDP broadcast."""
        mac_lower = mac.lower()
        if mac_lower in self._ip_cache:
            return self._ip_cache[mac_lower]

        from .kelvinator_dna.device import discover_devices
        try:
            devices = discover_devices(timeout=3.0)
            for d in devices:
                d_mac = d["mac"].lower()
                self._ip_cache[d_mac] = d["ip"]
                _LOGGER.info("LAN discovered: %s @ %s", d_mac, d["ip"])
        except Exception as exc:
            _LOGGER.debug("LAN discovery error: %s", exc)

        return self._ip_cache.get(mac_lower)


# ---------------------------------------------------------------------------
# Device wrapper
# ---------------------------------------------------------------------------


class KelvinatorACDevice:
    """Kelvinator AC unit controlled via kelvinator_dna (cloud relay or local UDP)."""

    def __init__(
        self,
        info: CloudDeviceInfo,
        relay: Optional[DNACloudRelay] = None,
    ) -> None:
        self.info = info
        self._relay = relay
        self.state = AcDeviceState()
        self.available = True

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def mac(self) -> str:
        return self.info.mac

    @property
    def did(self) -> str:
        return self.info.did

    async def update_state(self) -> bool:
        if self._relay is None:
            return True
        try:
            config = _json.dumps({
                "did": self.did,
                "mac": self.mac,
                "aes_key": self.info.aes_key,
                "password": self.info.password,
            })
            result = await asyncio.to_thread(self._relay.get_status, config)
            if result.get("status") == 0:
                data = result.get("data", {})
                self.state.power = bool(data.get("ac_pwr", 0))
                self.state.mode = data.get("ac_mode", 0)
                self.state.target_temp = data.get("temp", 24)
                self.state.fan = data.get("ac_mark", 0)
                self.state.ambient_temp = float(data.get("envtemp", 0))
                self.state.error_code = int(data.get("ac_errcode", 0))
                self.state.swing = data.get("ac_vdir", 0)
                self.state.sleep = bool(data.get("ac_slp", 0))
                self.available = True
                return True
        except Exception as exc:
            _LOGGER.warning("Status query failed for %s: %s", self.name, exc)
            self.available = False
        return False

    async def send_command(self, params: dict) -> bool:
        if self._relay is None:
            _LOGGER.warning("No cloud relay available for %s", self.name)
            return False
        try:
            cmd = _json.dumps({"did": self.did, "params": params})
            result = await asyncio.to_thread(
                self._relay.send_command,
                did=self.did, mac=self.mac,
                aes_key=self.info.aes_key, password=self.info.password,
                command_json=cmd,
            )
            return result.get("status") == 0
        except Exception as exc:
            _LOGGER.error("Command failed for %s: %s", self.name, exc)
            return False


# Backward compatibility alias
CloudACDevice = KelvinatorACDevice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_dna_relay() -> Optional[DNACloudRelay | DNALocalRelay]:
    """Get the DNA relay — cloud relay preferred, local UDP as fallback."""
    if _SO_AVAILABLE:
        try:
            return DNACloudRelay()
        except Exception as exc:
            _LOGGER.warning("Failed to init cloud relay: %s", exc)
    _LOGGER.info("Cloud relay unavailable — using local UDP control")
    return DNALocalRelay()
