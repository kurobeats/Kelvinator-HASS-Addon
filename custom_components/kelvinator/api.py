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
import re
import socket
import struct
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
    Local UDP control using python-broadlink for transport.

    Uses the standard BroadLink protocol (hello → auth → send_packet(0x6A, …))
    which these Electrolux/Kelvinator ACs (devtype 0x4F9B/20379) speak natively.

    AC commands are serialised as JSON mimicking the Java BLStdControlParam
    structure that the official Electrolux app passes to dnaControl():
      {"act": "get|set", "params": ["ac_pwr", …], "vals": [[…], …]}

    The payload is AES-128-CBC encrypted with the per-device cloud key
    (same key retrieved from the BroadLink cloud API).
    """

    # Devtype for Electrolux / Kelvinator AC units
    AC_DEVTYPE = 0x4F9B  # 20379

    def __init__(self) -> None:
        self._devices: dict[str, "_BroadlinkDevice"] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface (matches DNACloudRelay)
    # ------------------------------------------------------------------

    def send_command(
        self,
        did: str, mac: str, aes_key: str, password: int, command_json: str,
    ) -> dict:
        """Send a control command to the device via local UDP."""
        try:
            dev = self._get_device(did, mac, aes_key)
            cmd = _json.loads(command_json)
            params: dict = cmd.get("params", {})

            # Build BLStdControlParam-style param/vals
            param_names: list[str] = []
            vals: list[list[dict]] = []

            for key, val in params.items():
                param_names.append(key)
                vals.append([{"idx": 1, "val": int(val) if isinstance(val, (int, bool)) else val}])

            if not param_names:
                return {"status": 0}

            pkt = _json.dumps({
                "act": "set",
                "params": param_names,
                "vals": vals,
            }, separators=(",", ":"))

            self._send_encrypted(dev, pkt)
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

            dev = self._get_device(did, mac, aes_key)

            pkt = _json.dumps({"act": "get"}, separators=(",", ":"))
            resp = self._send_encrypted(dev, pkt)

            result = _json.loads(resp)
            if result.get("status") != 0:
                _LOGGER.warning("Status query returned error: %s", result)
                return {"status": -1, "message": result.get("msg", "Unknown error")}

            raw = result.get("data", {})
            return {
                "status": 0,
                "data": {
                    "ac_pwr": int(raw.get("ac_pwr", 0)),
                    "ac_mode": int(raw.get("ac_mode", 0)),
                    "temp": int(float(raw.get("temp", 24))),
                    "ac_mark": int(raw.get("ac_mark", 0)),
                    "envtemp": float(raw.get("envtemp", 0)),
                    "ac_errcode": int(raw.get("ac_errcode", 0)),
                    "ac_vdir": int(raw.get("ac_vdir", 0)),
                    "ac_slp": int(raw.get("ac_slp", 0)),
                    "ac_hdir": int(raw.get("ac_hdir", 0)),
                },
            }
        except Exception as exc:
            _LOGGER.error("Local status failed: %s", exc)
            return {"status": -1, "message": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_encrypted(self, dev: "_BroadlinkDevice", plaintext: str) -> str:
        """Encrypt JSON, send via 0x6A, decrypt response."""
        import broadlink

        payload = plaintext.encode("utf-8")
        # Pad to 16-byte boundary with PKCS#7
        pad_len = 16 - (len(payload) % 16)
        payload += bytes([pad_len] * pad_len)

        encrypted = dev._encrypt(payload)
        resp = dev.broadlink.send_packet(0x6A, encrypted)
        broadlink.exceptions.check_error(resp[0x22:0x24])

        decrypted = dev._decrypt(resp[0x38:])
        # Remove PKCS#7 padding
        if decrypted:
            pad_len = decrypted[-1]
            if 1 <= pad_len <= 16:
                decrypted = decrypted[:-pad_len]
        return decrypted.decode("utf-8")

    def _get_device(
        self, did: str, mac: str, aes_key: str,
    ) -> "_BroadlinkDevice":
        """Get or create a BroadLink device wrapper for the given MAC/DID."""
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
            dev = _BroadlinkDevice(
                ip=ip, mac=mac, aes_key=aes_key, devtype=self.AC_DEVTYPE,
            )
            dev.connect()
            self._devices[did] = dev
            _LOGGER.info("Local device connected: %s @ %s", mac, ip)
        return self._devices[did]

    def _discover_ip(self, mac: str) -> Optional[str]:
        """Find the LAN IP for a given MAC address."""
        import broadlink

        mac_lower = mac.lower()

        # Try direct hello (the device IS on the same subnet)
        for ip_suffix in range(150, 160):
            ip = f"172.16.23.{ip_suffix}"
            try:
                dev = broadlink.hello(ip, port=80, timeout=2)
                if dev.mac.hex().lower() == mac_lower:
                    _LOGGER.info("Discovered: %s @ %s", mac, ip)
                    return ip
            except Exception:
                pass

        # Fall back to ARP
        try:
            with open("/proc/net/arp") as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[3].lower() == mac_lower:
                        return parts[0]
        except Exception:
            pass
        return None


class _BroadlinkDevice:
    """Thin wrapper around a python-broadlink Device with cloud-key encryption."""

    # Hardcoded AES IV (same for ALL BroadLink devices)
    _IV = bytes.fromhex("562e17996d093d28ddb3ba695a2e6f58")

    def __init__(self, ip: str, mac: str, aes_key: str, devtype: int) -> None:
        self.ip = ip
        self.mac = mac
        self._devtype = devtype
        self.broadlink = None

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        self._aes_key = bytes.fromhex(aes_key)
        self._Cipher = Cipher
        self._algorithms = algorithms
        self._modes = modes
        self._default_backend = default_backend

    def connect(self) -> None:
        """Discover and authenticate with the device."""
        import broadlink

        self.broadlink = broadlink.hello(self.ip, port=80, timeout=5)
        self.broadlink.auth()
        _LOGGER.info("BroadLink auth OK for %s (id=%s)", self.ip, self.broadlink.id)

    def _encrypt(self, data: bytes) -> bytes:
        """AES-128-CBC encrypt with the cloud key."""
        cipher = self._Cipher(
            self._algorithms.AES(self._aes_key),
            self._modes.CBC(self._IV),
            backend=self._default_backend(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(data) + encryptor.finalize()

    def _decrypt(self, data: bytes) -> bytes:
        """AES-128-CBC decrypt with the cloud key."""
        cipher = self._Cipher(
            self._algorithms.AES(self._aes_key),
            self._modes.CBC(self._IV),
            backend=self._default_backend(),
        )
        decryptor = cipher.decryptor()
        return decryptor.update(data) + decryptor.finalize()


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
