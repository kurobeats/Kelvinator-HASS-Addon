"""
Kelvinator Home Comfort — API layer.

Cloud (HTTPS REST, kelvinator_dna.cloud) for login + device discovery with
AES keys.  Control/status goes through the bundled BroadLink DNA SDK
native bridge (dna_native.py → dna_sdk/) using the SDK's own script-driven
protocol (DNA Kit Lua scripts), matching the official app.
"""

from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from .const import DEFAULT_LICENSE_ID, COMPANY_ID, AES_IV, PASSWORD_SALT, TIMESTAMP_SALT, TOKEN_SALT
from .dna_native import NativeDNAClient, NativeDNAError

_LOGGER = logging.getLogger(__name__)

# DNA Kit parameter names (from the decrypted 9b4f0000 DNA Kit Lua script).
# These are STRING names on the wire (JSON body), not binary IDs.
DNA_PARAMS_STATUS = [
    "ac_pwr", "ac_mode", "temp", "ac_mark", "ac_vdir", "ac_slp",
    "scrdisp", "ecomode", "envtemp", "ac_errcode",
]

# HA-side shortcut → DNA param name
_PARAM_MAP = {
    "power": "ac_pwr",
    "mode": "ac_mode",
    "temp": "temp",
    "fan": "ac_mark",
    "vdir": "ac_vdir",
    "sleep": "ac_slp",
    "scrdisp": "scrdisp",
    "ecomode": "ecomode",
}

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
    mode: int = 0       # 0=cool, 1=heat, 2=dry, 3=fan, 4=auto
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
    """Blocking cloud login matching the official app SDK.

    Password: SHA1(SHA256(password + PASSWORD_SALT)) per BLCommonTools.SHA1().
    Encryption: AES-128-CBC with PKCS7 padding (deliberate revert; verified
    working against the live server — see git history aa2cc77).
    Key: MD5(timestamp + TIMESTAMP_SALT) per BLCommonTools.md5().
    Token: MD5(body_json + TOKEN_SALT).

    Validated against decompiled SDK:
      - cn.com.broadlink.sdk.a.a() — HTTP post with AES encoding
      - cn.com.broadlink.base.BLCommonTools.SHA1() — SHA256→SHA1 chain
      - cn.com.broadlink.base.BLCommonTools.aesNoPadding() — ZeroBytePadding
    """
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
        _LOGGER.debug("Cloud login OK (uid=%s)", user_id[:8] + "...")

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

    async def sdk_auth_params(self) -> Optional[list[str]]:
        """Fetch the API key + timestamp needed for the native SDKAuth call."""
        from .kelvinator_dna.cloud import KelvinatorCloud

        cloud = KelvinatorCloud(
            license_id=self._license_id,
            user_id=self._userid or "",
            login_session=self._loginsession or "",
            language=self._language,
        )
        try:
            api_key = await asyncio.to_thread(cloud.authenticate)
        except Exception as exc:
            _LOGGER.warning("Could not obtain API key for SDKAuth: %s", exc)
            return None
        ts = str(cloud.credentials.server_timestamp or int(time.time()))
        return [api_key, ts]


# ---------------------------------------------------------------------------
# DNA SDK native bridge control
# ---------------------------------------------------------------------------


class KelvinatorACDevice:
    """Kelvinator AC unit controlled via the bundled DNA SDK native bridge."""

    def __init__(self, info: CloudDeviceInfo, client: Optional[NativeDNAClient] = None) -> None:
        self.info = info
        self._client = client
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

    def _dev_dict(self) -> dict[str, Any]:
        return {
            "did": self.info.did,
            "mac": self.info.mac.replace(":", ""),
            "aes_key": self.info.aes_key,
            "password": self.info.password,
            "pid": self.info.pid,
            "devtype": self.info.devtype,
            "magiccode": self.info.pid or "9b4f0000",
            "ip": getattr(self, "_ip", "") or "",
            "port": 80,
        }

    async def update_state(self) -> bool:
        if self._client is None:
            return False
        try:
            dev = self._dev_dict()
            vals = [[{"val": 0}] for _ in DNA_PARAMS_STATUS]
            resp = await self._client.device_request(dev, "get", DNA_PARAMS_STATUS, vals)
            data = resp.get("data") or {}
            recv = data.get("recvData")
            values: dict[str, Any] = {}
            if recv:
                import base64
                body = _json.loads(base64.b64decode(recv))
                values = body if isinstance(body, dict) else {}
            elif data.get("params"):
                # some SDK versions return parsed params directly
                values = dict(zip(data["params"],
                                  [v[0]["val"] for v in data.get("vals", [])]))
            else:
                _LOGGER.warning(
                    "Status query for %s returned no data: %s — DNA SDK auth "
                    "(SDKAuth) may be required (control key expired)",
                    self.name, resp)
                self.available = False
                return False
            self.state.power = bool(values.get("ac_pwr", 0))
            self.state.mode = int(values.get("ac_mode", 0))
            self.state.target_temp = int(values.get("temp", 24))
            self.state.fan = int(values.get("ac_mark", 0))
            self.state.swing = int(values.get("ac_vdir", 0))
            self.state.sleep = bool(values.get("ac_slp", 0))
            self.state.display_on = bool(values.get("scrdisp", 1))
            self.state.eco = bool(values.get("ecomode", 0))
            self.state.ambient_temp = float(values.get("envtemp", 0))
            self.state.error_code = int(values.get("ac_errcode", 0))
            self.available = True
            return True
        except NativeDNAError as exc:
            _LOGGER.warning("Status query failed for %s: %s", self.name, exc)
            self.available = False
        except Exception as exc:
            _LOGGER.warning("Status query error for %s: %s", self.name, exc)
            self.available = False
        return False

    async def send_command(self, params: dict) -> bool:
        if self._client is None:
            _LOGGER.warning("No DNA SDK bridge available for %s", self.name)
            return False
        try:
            names = [_PARAM_MAP.get(k, k) for k in params]
            vals = [[{"val": v}] for v in params.values()]
            dev = self._dev_dict()
            resp = await self._client.device_request(dev, "set", names, vals)
            ok = resp.get("status") == 0
            if not ok:
                _LOGGER.warning("Command rejected for %s: %s", self.name, resp)
            self.available = ok
            return ok
        except NativeDNAError as exc:
            _LOGGER.error("Command failed for %s: %s", self.name, exc)
            self.available = False
            return False


# Backward compatibility alias
CloudACDevice = KelvinatorACDevice
