"""
Kelvinator Home Comfort — API layer.

Contains:
  - Cryptographic helpers (matching the BroadLink app's BLCommonTools)
  - BroadLink Cloud API client (async, aiohttp-based)
  - Device client wrapping python-broadlink for LAN/cloud relay control

All logic is extracted from the original add-on; no guessing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Optional

import aiohttp
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from .const import (
    AC_DEVICE_TYPES,
    AES_IV,
    BASE_ACCOUNT,
    BASE_ELECTROLUX,
    BASE_FAMILY,
    DEFAULT_LICENSE_ID,
    FULL_LICENSE,
    KEY_PERMUTATION,
    PASSWORD_SALT,
    TIMESTAMP_SALT,
    TOKEN_SALT,
    AcMode,
    FanSpeed,
    FAN_HA_TO_KELVINATOR,
    MODE_HA_TO_KELVINATOR,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cryptographic helpers — matching BLCommonTools from decompiled APK
# ---------------------------------------------------------------------------


def _md5(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.md5(data).hexdigest().lower()


def _sha1(data: str) -> str:
    return hashlib.sha1(data.encode()).hexdigest().lower()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest().lower()


def _parse_hex_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)


def _permute_key(md5_hex: str) -> bytes:
    """Apply key permutation from aeskeyDecrypt()."""
    md5_bytes = _parse_hex_to_bytes(md5_hex)
    key = bytearray(16)
    for i, idx in enumerate(KEY_PERMUTATION):
        key[i] = md5_bytes[idx]
    return bytes(key)


def _encrypt_body(plaintext: str, timestamp: str) -> str:
    """
    AES/CBC/ZeroBytePadding encryption matching BLCommonTools.aesNoPadding().
    1. key = MD5(timestamp + TIMESTAMP_SALT) → hex → permute
    2. AES/CBC with hardcoded IV
    3. Return hex-encoded ciphertext
    """
    md5_key_hex = _md5(timestamp + TIMESTAMP_SALT)
    aes_key = _permute_key(md5_key_hex)
    data = plaintext.encode("utf-8")
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=AES_IV)
    padded = pad(data, AES.block_size)
    return cipher.encrypt(padded).hex()


def _make_token(plaintext: str) -> str:
    return _md5(plaintext + TOKEN_SALT)


def _hash_password(raw_password: str) -> str:
    """SHA1(SHA256(raw) + PASSWORD_SALT)."""
    return _sha1(_sha256(raw_password) + PASSWORD_SALT)


# ---------------------------------------------------------------------------
# BroadLink Cloud API Client (async, aiohttp)
# ---------------------------------------------------------------------------


class BroadLinkCloudClient:
    """Authenticated async client for the BroadLink cloud API."""

    def __init__(
        self,
        license_id: str = DEFAULT_LICENSE_ID,
        country_code: str = "61",
        timeout: int = 15,
    ) -> None:
        self._license_id = license_id
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._headers = {
            "Content-Type": "text/plain;charset=utf-8",
            "system": "android",
            "appPlatform": "android",
            "appVersion": "3.8.2",
        }

        # Locale — maps country code to BroadLink locate/language format
        # From BLCommonUtils.getCountry() / getLanguage()
        self._locate = country_code
        self._language = "en"

        # Auth state
        self._userid: Optional[str] = None
        self._loginsession: Optional[str] = None
        self._nickname: Optional[str] = None

    # -------------------------------------------------- Session management

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout, headers=self._headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # -------------------------------------------------- URL helpers

    def _account_url(self, path: str) -> str:
        return BASE_ACCOUNT.format(self._license_id) + path

    def _family_url(self, path: str) -> str:
        return BASE_FAMILY.format(self._license_id) + path

    def _electrolux_url(self, path: str) -> str:
        return BASE_ELECTROLUX.format(self._license_id) + path

    # -------------------------------------------------- HTTP

    async def _encrypted_post(self, url: str, body: dict, extra_headers: dict | None = None) -> dict:
        """POST with AES-encrypted body, MD5 token, and additional headers."""
        session = await self._ensure_session()
        timestamp = str(int(time.time()))
        plaintext = json.dumps(body, separators=(",", ":"))
        ciphertext = _encrypt_body(plaintext, timestamp)
        token = _make_token(plaintext)

        headers = {
            "timestamp": timestamp,
            "token": token,
            "language": self._language,
            "locate": self._locate,
            "licenseid": self._license_id,
        }
        if self._userid:
            headers["userid"] = self._userid
        if extra_headers:
            headers.update(extra_headers)

        _LOGGER.debug("POST %s body=%s", url, plaintext)
        async with session.post(url, data=ciphertext, headers=headers) as resp:
            text = await resp.text()
            _LOGGER.debug("Response [%d]: %s", resp.status, text[:500])
            return json.loads(text)

    # -------------------------------------------------- Auth

    async def login(self, username: str, password: str) -> dict:
        """Authenticate with BroadLink account. Raises on failure."""
        body = {
            "password": _hash_password(password),
            "companyid": FULL_LICENSE,
        }
        if "@" in username:
            body["email"] = username
        else:
            body["phone"] = username

        try:
            result = await self._encrypted_post(
                self._account_url("/account/login"), body
            )
        except aiohttp.ClientError as exc:
            _LOGGER.error("Login request failed: %s", exc)
            raise RuntimeError(f"Login request failed: {exc}") from exc

        if result.get("error") != 0:
            msg = result.get("msg", result.get("message", "Unknown error"))
            raise RuntimeError(
                f"Login failed: {msg} (code={result.get('error')})"
            )

        self._userid = result.get("userid")
        self._loginsession = result.get("loginsession")
        self._nickname = result.get("nickname")
        _LOGGER.info("Logged in as %s (uid=%s)", self._nickname, self._userid)
        return result

    @property
    def userid(self) -> Optional[str]:
        return self._userid

    @property
    def is_logged_in(self) -> bool:
        return self._loginsession is not None

    # -------------------------------------------------- Device list

    async def get_family_base_info_list(self) -> dict:
        """Get base info for all families/device groups."""
        return await self._encrypted_post(
            self._family_url("/ec4/v1/user/getbasefamilylist"),
            {"userid": self._userid or ""},
        )

    async def get_family_all_info(self, family_id: str) -> dict:
        """Get full family info including device list."""
        return await self._encrypted_post(
            self._family_url("/ec4/v1/family/getallinfo"),
            {"familyid": family_id},
        )

    async def list_devices(self) -> list[dict]:
        """
        Return all cloud-registered devices for the logged-in account.

        Returns a list of dicts with keys: name, mac, host, did, pid.
        """
        devices: list[dict] = []
        info = await self.get_family_base_info_list()
        if info.get("error") != 0:
            _LOGGER.warning("get_family_base_info_list failed: %s", info)
            return []

        families = info.get("familyBaseInfoList", info.get("data", []))
        if isinstance(families, list):
            for fam in families:
                fam_id = fam.get("familyid", fam.get("familyId", ""))
                if not fam_id:
                    continue
                fam_info = await self.get_family_all_info(fam_id)
                if fam_info.get("error") != 0:
                    continue
                dev_list = fam_info.get("deviceinfo", fam_info.get("data", {}))
                if isinstance(dev_list, list):
                    for dev in dev_list:
                        devices.append({
                            "name": dev.get("name", ""),
                            "mac": dev.get("mac", ""),
                            "host": dev.get("host", ""),
                            "did": dev.get("did", ""),
                            "pid": dev.get("pid", ""),
                        })
        return devices


# ---------------------------------------------------------------------------
# Device state model
# ---------------------------------------------------------------------------


class AcDeviceState:
    """Full state of a Kelvinator AC unit, normalized for HA."""

    __slots__ = (
        "power", "mode", "target_temp", "fan_speed",
        "swing_vertical", "swing_horizontal",
        "sleep", "eco", "display_on", "temp_unit_celsius",
        "ambient_temp", "error_code",
        "temp_min_c", "temp_max_c",
        "model_number", "serial_number",
        "timer", "schedule_enabled", "schedule_time",
    )

    def __init__(self) -> None:
        self.power: bool = False
        self.mode: AcMode = AcMode.AUTO
        self.target_temp: int = 24
        self.fan_speed: FanSpeed = FanSpeed.AUTO
        self.swing_vertical: bool = False
        self.swing_horizontal: bool = False
        self.sleep: bool = False
        self.eco: bool = False
        self.display_on: bool = True
        self.temp_unit_celsius: bool = True
        self.ambient_temp: float = 0.0
        self.error_code: str = "0"
        self.temp_min_c: int = 16
        self.temp_max_c: int = 30
        self.model_number: str = ""
        self.serial_number: str = ""
        self.timer: str = ""
        self.schedule_enabled: bool = False
        self.schedule_time: str = ""


# ---------------------------------------------------------------------------
# Device client — wraps python-broadlink (LAN / cloud relay)
# ---------------------------------------------------------------------------


class KelvinatorACDevice:
    """Represents a single Kelvinator AC unit via BroadLink DNA protocol."""

    def __init__(
        self,
        host: str,
        mac: str,
        name: str = "Kelvinator AC",
        timeout: int = 5,
    ) -> None:
        self._host = host
        self._mac = mac
        self._name = name
        self._timeout = timeout
        self._device: Any = None
        self.state = AcDeviceState()
        self.available: bool = False

    # -------------------------------------------------- Properties

    @property
    def name(self) -> str:
        return self._name

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def host(self) -> str:
        return self._host

    # -------------------------------------------------- Connection

    async def connect(self) -> bool:
        """Connect to the device over LAN using python-broadlink."""
        try:
            import broadlink

            self._device = await asyncio.to_thread(
                broadlink.hello, self._host
            )
            if self._device is None:
                _LOGGER.warning(
                    "No BroadLink device at %s (MAC=%s)",
                    self._host, self._mac,
                )
                self.available = False
                return False

            if hasattr(self._device, "auth"):
                await asyncio.to_thread(self._device.auth)

            self.available = True
            _LOGGER.info(
                "Connected to %s [%s] type=0x%04X",
                self._name, self._mac, self._device.type,
            )
            return True

        except Exception as exc:
            _LOGGER.error("Failed to connect to %s: %s", self._name, exc)
            self.available = False
            return False

    # -------------------------------------------------- State polling

    async def update_state(self) -> bool:
        """Query full device state. Returns True on success."""
        if self._device is None:
            if not await self.connect():
                return False

        try:
            if hasattr(self._device, "get_state"):
                await asyncio.to_thread(self._device.get_state)
            if hasattr(self._device, "check_sensors"):
                await asyncio.to_thread(self._device.check_sensors)

            self._parse_device_state()
            self.available = True
            return True

        except Exception as exc:
            _LOGGER.warning(
                "Failed to update state for %s: %s", self._name, exc
            )
            self.available = False
            return False

    def _parse_device_state(self) -> None:
        """Extract Kelvinator params from broadlink device attributes."""
        dev = self._device
        if dev is None:
            return

        s = self.state
        s.power = bool(getattr(dev, "power", s.power))

        if hasattr(dev, "mode"):
            try:
                s.mode = AcMode(int(dev.mode))
            except (ValueError, TypeError):
                s.mode = AcMode.AUTO

        if hasattr(dev, "temp"):
            s.target_temp = int(dev.temp)

        if hasattr(dev, "fan_speed"):
            try:
                s.fan_speed = FanSpeed(int(dev.fan_speed))
            except (ValueError, TypeError):
                s.fan_speed = FanSpeed.AUTO

        s.swing_vertical = bool(getattr(dev, "swing_v", s.swing_vertical))
        s.swing_horizontal = bool(getattr(dev, "swing_h", s.swing_horizontal))
        s.sleep = bool(getattr(dev, "sleep", s.sleep))
        s.eco = bool(getattr(dev, "eco", s.eco))
        s.display_on = bool(getattr(dev, "display_on", s.display_on))
        s.ambient_temp = float(getattr(dev, "room_temp", s.ambient_temp))

        # Timer / schedule (read-only from LAN)
        if hasattr(dev, "timer"):
            s.timer = str(dev.timer or "")
        if hasattr(dev, "schedule_enabled"):
            s.schedule_enabled = bool(dev.schedule_enabled)
        if hasattr(dev, "schedule_time"):
            s.schedule_time = str(dev.schedule_time or "")

    # -------------------------------------------------- Commands

    async def _ensure_device(self) -> bool:
        if self._device is not None:
            return True
        return await self.connect()

    async def set_power(self, on: bool) -> bool:
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_power"):
                await asyncio.to_thread(dev.set_power, on)
            elif hasattr(dev, "power"):
                dev.power = on
            self.state.power = on
            return True
        except Exception as exc:
            _LOGGER.error("set_power(%s) failed: %s", on, exc)
            self.available = False
            return False

    async def set_mode(self, mode: AcMode) -> bool:
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_mode"):
                await asyncio.to_thread(dev.set_mode, int(mode))
            self.state.mode = mode
            return True
        except Exception as exc:
            _LOGGER.error("set_mode(%s) failed: %s", mode, exc)
            self.available = False
            return False

    async def set_temperature(self, temp_c: int) -> bool:
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            target = max(self.state.temp_min_c, min(self.state.temp_max_c, temp_c))
            if hasattr(dev, "set_temp"):
                await asyncio.to_thread(dev.set_temp, target)
            self.state.target_temp = target
            return True
        except Exception as exc:
            _LOGGER.error("set_temperature(%d) failed: %s", temp_c, exc)
            self.available = False
            return False

    async def set_fan_speed(self, speed: FanSpeed) -> bool:
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_fan_speed"):
                await asyncio.to_thread(dev.set_fan_speed, int(speed))
            self.state.fan_speed = speed
            return True
        except Exception as exc:
            _LOGGER.error("set_fan_speed(%s) failed: %s", speed, exc)
            self.available = False
            return False

    async def set_swing_v(self, on: bool) -> bool:
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_swing_v"):
                await asyncio.to_thread(dev.set_swing_v, on)
            self.state.swing_vertical = on
            return True
        except Exception as exc:
            _LOGGER.error("set_swing_v(%s) failed: %s", on, exc)
            self.available = False
            return False

    async def set_swing_h(self, on: bool) -> bool:
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_swing_h"):
                await asyncio.to_thread(dev.set_swing_h, on)
            self.state.swing_horizontal = on
            return True
        except Exception as exc:
            _LOGGER.error("set_swing_h(%s) failed: %s", on, exc)
            self.available = False
            return False

    async def set_display(self, on: bool) -> bool:
        """Toggle front panel display."""
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_display"):
                await asyncio.to_thread(dev.set_display, on)
            self.state.display_on = on
            return True
        except Exception as exc:
            _LOGGER.error("set_display(%s) failed: %s", on, exc)
            self.available = False
            return False

    async def set_sleep(self, on: bool) -> bool:
        """Toggle sleep mode."""
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_sleep"):
                await asyncio.to_thread(dev.set_sleep, on)
            self.state.sleep = on
            return True
        except Exception as exc:
            _LOGGER.error("set_sleep(%s) failed: %s", on, exc)
            self.available = False
            return False

    async def set_eco(self, on: bool) -> bool:
        """Toggle ECO mode."""
        if not await self._ensure_device():
            return False
        try:
            dev = self._device
            if hasattr(dev, "set_eco"):
                await asyncio.to_thread(dev.set_eco, on)
            self.state.eco = on
            return True
        except Exception as exc:
            _LOGGER.error("set_eco(%s) failed: %s", on, exc)
            self.available = False
            return False

    async def set_hvac_mode(self, ha_mode: str) -> bool:
        """Set HA HVAC mode. 'off' = power off, otherwise power on + set mode."""
        if ha_mode == "off":
            return await self.set_power(False)

        kelvinator_mode = MODE_HA_TO_KELVINATOR.get(ha_mode)
        if kelvinator_mode is None:
            _LOGGER.warning("Unknown HVAC mode: %s", ha_mode)
            return False

        if not self.state.power:
            if not await self.set_power(True):
                return False
        return await self.set_mode(kelvinator_mode)

    async def set_fan_mode(self, ha_fan: str) -> bool:
        """Set HA fan mode."""
        speed = FAN_HA_TO_KELVINATOR.get(ha_fan)
        if speed is None:
            _LOGGER.warning("Unknown fan mode: %s", ha_fan)
            return False
        return await self.set_fan_speed(speed)

    async def set_swing_mode(self, ha_swing: str) -> bool:
        """Set HA swing mode."""
        if ha_swing == "off":
            rv = await self.set_swing_v(False)
            rh = await self.set_swing_h(False)
            return rv and rh
        elif ha_swing == "vertical":
            return await self.set_swing_v(True)
        elif ha_swing == "horizontal":
            return await self.set_swing_h(True)
        elif ha_swing == "both":
            rv = await self.set_swing_v(True)
            rh = await self.set_swing_h(True)
            return rv and rh
        return False


# ---------------------------------------------------------------------------
# Discovery helper
# ---------------------------------------------------------------------------


async def discover_devices(timeout: int = 5) -> list[KelvinatorACDevice]:
    """Discover BroadLink DNA AC devices on the LAN via UDP broadcast."""
    try:
        import broadlink
    except ImportError:
        _LOGGER.error("broadlink library not installed")
        return []

    devices: list[KelvinatorACDevice] = []
    try:
        discovered = await asyncio.to_thread(broadlink.discover, timeout=timeout)
    except Exception as exc:
        _LOGGER.error("Discovery failed: %s", exc)
        return []

    for dev in discovered:
        if dev.devtype in AC_DEVICE_TYPES:
            host = dev.host[0]
            mac = dev.mac.hex()
            devices.append(
                KelvinatorACDevice(
                    host=host,
                    mac=mac,
                    name=f"Kelvinator-{mac[-4:]}",
                )
            )
            _LOGGER.info("Discovered: %s at %s [0x%04X]", mac, host, dev.devtype)

    return devices


async def probe_device(host: str, timeout: int = 5) -> KelvinatorACDevice | None:
    """Directly probe a single IP address for a BroadLink AC device."""
    try:
        import broadlink
    except ImportError:
        _LOGGER.error("broadlink library not installed")
        return None

    try:
        dev = await asyncio.to_thread(broadlink.hello, host)
    except Exception as exc:
        _LOGGER.error("Probe failed for %s: %s", host, exc)
        return None

    if dev is None:
        _LOGGER.warning("No BroadLink device at %s", host)
        return None

    mac = dev.mac.hex()
    _LOGGER.info("Probed device at %s: MAC=%s type=0x%04X", host, mac, dev.devtype)

    return KelvinatorACDevice(
        host=host,
        mac=mac,
        name=f"Kelvinator-{mac[-4:]}",
    )
