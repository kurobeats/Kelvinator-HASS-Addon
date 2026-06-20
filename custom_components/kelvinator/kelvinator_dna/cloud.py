"""
Cloud API: Interface with the BroadLink cloud service for device discovery
and credential retrieval for Kelvinator/Electrolux AC units.

The cloud API is a set of HTTPS REST endpoints hosted at:
  - bizihcv0.ibroadlink.com (main API, family/device management)
  - rccode.ibroadlink.com (remote control codes)

Authentication:
  - License ID: 32-char hex string unique per OEM/app installation
  - Login session: obtained via /ec4/v1/common/api
  - User ID: 32-char hex string unique per user account
  - Token: MD5-based session token for subsequent requests

API Endpoints:
  1. GET  /ec4/v1/common/api          -> Get API key (initial handshake)
  2. POST /ec4/v1/user/getfamilyid     -> Get family/home IDs
  3. POST /ec4/v1/family/getallinfo    -> Get all devices with AES keys
"""

import hashlib
import json
import logging
import time
import urllib.request
import urllib.error
import ssl
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AES constants (from decompiled BroadLink SDK)
# ---------------------------------------------------------------------------

AES_IV = bytes([
    0xEA, 0xAA, 0xAA, 0x3A, 0xBB, 0x58, 0x62, 0xA2,
    0x19, 0x18, 0xB5, 0x77, 0x1D, 0x16, 0x15, 0xAA,
])
TOKEN_SALT = "xgx3d*fe3478$ukx"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Information about a discovered AC device from the cloud API."""
    did: str                    # Device ID (34 hex chars = 17 bytes)
    mac: str                    # MAC address (colon-separated hex)
    name: str                   # User-assigned device name
    devtype: int                # Device type (e.g., 20379 = AC)
    pid: str                    # Product ID
    password: int               # Device password (4-byte key for auth XOR)
    aes_key: str                # AES-128 key (32 hex chars = 16 bytes)
    terminal_id: int            # Terminal ID
    sub_device_num: int         # Number of sub-devices
    room_id: str                # Room ID
    room_name: str = ""         # Room name


@dataclass
class CloudCredentials:
    """Credentials for accessing the BroadLink cloud API."""
    license_id: str             # 32-char hex OEM license ID
    user_id: str                # 32-char hex user ID
    login_session: str          # 32-char hex login session
    api_key: str = ""           # API key from /ec4/v1/common/api
    token: str = ""             # Auth token for subsequent requests
    server_timestamp: int = 0   # Timestamp from /ec4/v1/common/api


# ---------------------------------------------------------------------------
# KelvinatorCloud Client
# ---------------------------------------------------------------------------

class KelvinatorCloud:
    """
    Client for the BroadLink cloud API specific to Kelvinator/Electrolux AC.

    Usage:
        cloud = KelvinatorCloud(license_id="bddb...")
        cloud.authenticate()
        devices = cloud.discover_devices()
        for dev in devices:
            print(f"{dev.name}: {dev.mac}, AES key: {dev.aes_key}")
    """

    API_HOST = "bddb4af53f74edaa03b1aa439b75e7a6bizihcv0.ibroadlink.com"

    def __init__(
        self,
        license_id: str,
        user_id: str = "",
        login_session: str = "",
        system: str = "android",
        app_platform: str = "android",
        language: str = "en-au",
    ):
        self.credentials = CloudCredentials(
            license_id=license_id,
            user_id=user_id,
            login_session=login_session,
        )
        self.system = system
        self.app_platform = app_platform
        self.language = language
        self._family_id: str = ""
        self._server_key: bytes = b""
        self.user_agent = (
            "Dalvik/2.1.0 (Linux; U; Android 16; SM-S926B Build/BP4A.251205.006)"
        )

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _make_request(
        self,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        host: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Make an HTTPS request to the BroadLink cloud API."""
        url = f"https://{host or self.API_HOST}{path}"

        headers = {
            "User-Agent": self.user_agent,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }
        if extra_headers:
            headers.update(extra_headers)
        if body:
            headers["Content-Length"] = str(len(body))

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                raw = resp.read()
                text = raw.decode('utf-8')
                return json.loads(text)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"HTTP {e.code}: {body_text}")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> str:
        """
        Perform cloud authentication.

        Step 1: Get API key and server timestamp from /ec4/v1/common/api
        """
        timestamp = int(time.time())

        headers = {
            "system": self.system,
            "appPlatform": self.app_platform,
            "language": self.language,
            "timestamp": str(timestamp),
            "Host": self.API_HOST,
        }
        resp = self._make_request("GET", "/ec4/v1/common/api", extra_headers=headers)
        self.credentials.api_key = resp.get("key", "")
        self.credentials.server_timestamp = resp.get("timestamp", timestamp)
        self._server_key = b""
        _LOGGER.info("API key obtained (server_ts=%d)", self.credentials.server_timestamp)
        return self.credentials.api_key

    # ------------------------------------------------------------------
    # Family / Home
    # ------------------------------------------------------------------

    def get_family_id(self) -> str:
        """Get the family (home) ID for the user."""
        timestamp = self.credentials.server_timestamp or int(time.time())

        body_json = json.dumps(
            {"userid": self.credentials.user_id}, separators=(",", ":")
        )
        encrypted_body = self._encrypt_family_body(body_json)
        headers = self._build_family_headers(body_json, timestamp)

        resp = self._make_request(
            "POST", "/ec4/v1/user/getfamilyid",
            body=encrypted_body, extra_headers=headers,
        )

        family_info = resp.get("familyinfo", [])
        if family_info:
            fid = family_info[0].get("id", "")
            _LOGGER.info("Family ID: %s", fid)
            self._family_id = fid
            return fid

        _LOGGER.warning("No family info in response: %s", resp)
        return ""

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def get_all_devices(self) -> Dict[str, Any]:
        """Get all device information including AES keys from the cloud."""
        if not self._family_id:
            self.get_family_id()
        if not self._family_id:
            _LOGGER.error("Cannot get devices: no family ID")
            return {}

        timestamp = self.credentials.server_timestamp or int(time.time())

        body_json = json.dumps({
            "userid": self.credentials.user_id,
            "familyid": [self._family_id],
        }, separators=(",", ":"))
        encrypted_body = self._encrypt_family_body(body_json)
        headers = self._build_family_headers(body_json, timestamp)

        return self._make_request(
            "POST", "/ec4/v1/family/getallinfo",
            body=encrypted_body, extra_headers=headers,
        )

    def discover_devices(self) -> List[DeviceInfo]:
        """Discover all AC devices linked to the user account."""
        data = self.get_all_devices()
        if not data:
            return []

        devices: List[DeviceInfo] = []
        family_data = data.get("familyallinfo", [{}])[0]

        rooms: Dict[str, str] = {}
        for room in family_data.get("roominfo", []):
            rooms[room.get("roomid", "")] = room.get("name", "")

        module_dids: Dict[str, str] = {}
        for mod in family_data.get("moduleinfo", []):
            for mdev in mod.get("moduledev", []):
                module_dids[mdev.get("did", "")] = mod.get("name", "")

        for dev in family_data.get("devinfo", []):
            did = dev.get("did", "")
            device = DeviceInfo(
                did=did,
                mac=dev.get("mac", ""),
                name=dev.get("name", "") or module_dids.get(did, ""),
                devtype=dev.get("devtype", 0),
                pid=dev.get("pid", ""),
                password=dev.get("password", 0),
                aes_key=dev.get("aeskey", ""),
                terminal_id=dev.get("terminalid", 1),
                sub_device_num=dev.get("subdevicenum", 0),
                room_id=dev.get("roomid", ""),
                room_name=rooms.get(dev.get("roomid", ""), ""),
            )
            devices.append(device)

        _LOGGER.info("Discovered %d device(s) in cloud account", len(devices))
        return devices

    # ------------------------------------------------------------------
    # Encryption helpers (Family API)
    # ------------------------------------------------------------------

    def _encrypt_family_body(self, plaintext: str) -> bytes:
        """
        AES-CBC encrypt the JSON body using the server key from /ec4/v1/common/api.
        """
        if not self._server_key:
            self._server_key = bytes.fromhex(self.credentials.api_key)
        cipher = AES.new(self._server_key, AES.MODE_CBC, iv=AES_IV)
        return cipher.encrypt(pad(plaintext.encode(), AES.block_size))

    def _generate_family_token(self, plaintext: str, timestamp: int) -> str:
        """Generate MD5 token for Family API endpoints."""
        material = (
            plaintext + TOKEN_SALT + str(timestamp) + self.credentials.user_id
        )
        return hashlib.md5(material.encode()).hexdigest()

    def _build_family_headers(self, plaintext: str, timestamp: int) -> Dict[str, str]:
        """Build common headers for Family API POST requests."""
        return {
            "Content-type": "application/x-java-serialized-object",
            "system": self.system,
            "appPlatform": self.app_platform,
            "language": self.language,
            "loginsession": self.credentials.login_session,
            "lid": self.credentials.license_id,
            "userid": self.credentials.user_id,
            "timestamp": str(timestamp),
            "token": self._generate_family_token(plaintext, timestamp),
            "Host": self.API_HOST,
        }


# ---------------------------------------------------------------------------
# Device cache helpers
# ---------------------------------------------------------------------------

def load_cached_devices(filepath: str) -> List[DeviceInfo]:
    """Load cached device information from a JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)

    devices = []
    for dev in data.get("devices", []):
        devices.append(DeviceInfo(
            did=dev["did"],
            mac=dev["mac"],
            name=dev.get("name", ""),
            devtype=dev.get("devtype", 0),
            pid=dev.get("pid", ""),
            password=dev.get("password", 0),
            aes_key=dev["aes_key"],
            terminal_id=dev.get("terminal_id", 1),
            sub_device_num=dev.get("sub_device_num", 0),
            room_id=dev.get("room_id", ""),
            room_name=dev.get("room_name", ""),
        ))
    return devices


def save_cached_devices(devices: List[DeviceInfo], filepath: str) -> None:
    """Save device credentials to a JSON file."""
    data = {
        "devices": [
            {
                "did": d.did,
                "mac": d.mac,
                "name": d.name,
                "devtype": d.devtype,
                "pid": d.pid,
                "password": d.password,
                "aes_key": d.aes_key,
                "terminal_id": d.terminal_id,
                "sub_device_num": d.sub_device_num,
                "room_id": d.room_id,
                "room_name": d.room_name,
            }
            for d in devices
        ]
    }
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
