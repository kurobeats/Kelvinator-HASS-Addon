"""
Cloud API: Interface with the BroadLink cloud service for device discovery
and credential retrieval.

The cloud API is a set of HTTPS REST endpoints hosted at:
  - bizihcv0.ibroadlink.com (main API)
  - rccode.ibroadlink.com (remote control codes)

Authentication:
  - License ID: 32-char hex string unique per OEM/app installation
  - Login session: obtained via /ec4/v1/common/api
  - User ID: 32-char hex string unique per user account
  - Token: session token for subsequent requests

API Endpoints:
  1. GET  /ec4/v1/common/api          → Get API key (initial handshake)
  2. POST /ec4/v1/user/getfamilyid     → Get family/home IDs for the user
  3. POST /ec4/v1/family/getallinfo    → Get all devices with AES keys
  4. POST /data/v1/appdata/upload     → Upload app analytics data
"""

import hashlib
import json
import time
import urllib.request
import urllib.error
import ssl
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    """Information about a discovered AC device."""
    did: str            # Device ID (34 hex chars = 17 bytes)
    mac: str            # MAC address (aa:bb:cc:dd:ee:ff)
    name: str           # User-assigned device name
    devtype: int        # Device type (e.g., 20379 = AC)
    pid: str            # Product ID
    password: int       # Device password (4-byte key for auth)
    aes_key: str        # AES-128 key (32 hex chars = 16 bytes)
    terminal_id: int    # Terminal ID
    sub_device_num: int # Number of sub-devices
    room_id: str        # Room ID
    room_name: str = "" # Room name (filled if available)


@dataclass
class FamilyInfo:
    """Information about a home/family."""
    family_id: str      # Family ID (hex)
    family_name: str    # Family name
    rooms: List[Dict] = field(default_factory=list)
    modules: List[Dict] = field(default_factory=list)


@dataclass
class CloudCredentials:
    """Credentials for accessing the BroadLink cloud API."""
    license_id: str     # 32-char hex OEM license ID
    user_id: str        # 32-char hex user ID
    login_session: str  # 32-char hex session token
    api_key: str = ""   # API key from initial handshake
    token: str = ""     # Auth token for subsequent requests


class KelvinatorCloud:
    """
    Client for the BroadLink cloud API.

    Usage:
        cloud = KelvinatorCloud(license_id="bddb...")
        cloud.authenticate()
        devices = cloud.get_devices()
        for dev in devices:
            print(f"{dev.name}: {dev.mac}, AES key: {dev.aes_key}")
    """

    API_HOST = "bddb4af53f74edaa03b1aa439b75e7a6bizihcv0.ibroadlink.com"
    RCCODE_HOST = "bddb4af53f74edaa03b1aa439b75e7a6rccode.ibroadlink.com"
    BASE_URL = f"https://{API_HOST}"
    RCCODE_URL = f"https://{RCCODE_HOST}"

    def __init__(
        self,
        license_id: str,
        user_id: str = "",
        login_session: str = "",
        system: str = "android",
        app_platform: str = "android",
        language: str = "en-au",
    ):
        """
        Args:
            license_id: OEM license ID (32 hex chars)
            user_id: User account ID (32 hex chars, can be set later)
            login_session: Session ID (can be set after authentication)
            system: System identifier (default: "android")
            app_platform: Platform identifier (default: "android")
            language: Language code (default: "en-au")
        """
        self.credentials = CloudCredentials(
            license_id=license_id,
            user_id=user_id,
            login_session=login_session,
        )
        self.system = system
        self.app_platform = app_platform
        self.language = language
        self.user_agent = (
            f"Dalvik/2.1.0 (Linux; U; Android 16; SM-S926B Build/BP4A.251205.006)"
        )

    def _make_request(
        self,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        host: str = None,
        extra_headers: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTPS request to the BroadLink cloud API.

        Args:
            method: HTTP method (GET, POST)
            path: API path (e.g., /ec4/v1/common/api)
            body: Raw request body bytes
            host: Override API host
            extra_headers: Additional HTTP headers

        Returns:
            Parsed JSON response
        """
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

        # Allow self-signed / custom CA (for MITM analysis)
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

    def authenticate(self) -> str:
        """
        Perform cloud authentication.

        1. Get API key from /ec4/v1/common/api
        2. Get family ID from /ec4/v1/user/getfamilyid
        3. Get full device info from /ec4/v1/family/getallinfo

        Returns:
            API key string
        """
        timestamp = int(time.time())

        # Step 1: Get API key
        headers = {
            "system": self.system,
            "appPlatform": self.app_platform,
            "language": self.language,
            "timestamp": str(timestamp),
            "Host": self.API_HOST,
        }
        resp = self._make_request("GET", "/ec4/v1/common/api", extra_headers=headers)
        self.credentials.api_key = resp.get("key", "")
        return self.credentials.api_key

    def get_family_id(self) -> str:
        """
        Get the family (home) ID for the user.

        Requires: login_session, user_id, license_id to be set.

        Returns:
            Family ID string
        """
        timestamp = int(time.time())

        headers = {
            "Content-type": "application/x-java-serialized-object",
            "system": self.system,
            "appPlatform": self.app_platform,
            "language": self.language,
            "loginsession": self.credentials.login_session,
            "lid": self.credentials.license_id,
            "userid": self.credentials.user_id,
            "timestamp": str(timestamp),
            "token": self._generate_token(),
            "Host": self.API_HOST,
        }

        # Build the Java serialized object body
        # This is a simplified version; the real body is Java ObjectOutputStream
        body = self._build_java_serialized_body("getfamilyid")

        resp = self._make_request(
            "POST", "/ec4/v1/user/getfamilyid", body=body, extra_headers=headers
        )

        family_info = resp.get("familyinfo", [])
        if family_info:
            return family_info[0].get("id", "")
        return ""

    def get_all_devices(self) -> Dict[str, Any]:
        """
        Get all device information including AES keys.

        Returns:
            Full API response with family, rooms, devices, and modules
        """
        timestamp = int(time.time())

        headers = {
            "Content-type": "application/x-java-serialized-object",
            "system": self.system,
            "appPlatform": self.app_platform,
            "language": self.language,
            "loginsession": self.credentials.login_session,
            "lid": self.credentials.license_id,
            "userid": self.credentials.user_id,
            "timestamp": str(timestamp),
            "token": self._generate_token(),
            "Host": self.API_HOST,
        }

        body = self._build_java_serialized_body("getallinfo")

        return self._make_request(
            "POST", "/ec4/v1/family/getallinfo", body=body, extra_headers=headers
        )

    def discover_devices(self) -> List[DeviceInfo]:
        """
        Discover all AC devices linked to the account.

        Returns:
            List of DeviceInfo objects with AES keys and credentials
        """
        data = self.get_all_devices()
        devices = []

        family_data = data.get("familyallinfo", [{}])[0]

        # Build room lookup
        rooms = {}
        for room in family_data.get("roominfo", []):
            rooms[room.get("roomid", "")] = room.get("name", "")

        # Build module lookup (maps modules to DIDs)
        module_dids = {}
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

        return devices

    def _generate_token(self) -> str:
        """
        Generate an authentication token based on the session state.

        The token is derived from the login session and user credentials.
        This is a placeholder — the actual algorithm uses the native library.
        """
        # In practice, the token is computed by libNetworkAPI.so
        # We return a dummy for offline use
        material = f"{self.credentials.login_session}{self.credentials.user_id}"
        return hashlib.md5(material.encode()).hexdigest()

    def _build_java_serialized_body(self, action: str) -> bytes:
        """
        Build a Java ObjectOutputStream serialized body.

        The cloud API accepts application/x-java-serialized-object content.
        The body contains encrypted parameter data.

        Note: Full reverse-engineering of the Java serialization is complex.
        In practice, this library is designed to work with cached credentials.
        For a full implementation, you would use Java's ObjectOutputStream or
        a Python equivalent.

        Args:
            action: API action name

        Returns:
            Java serialized bytes
        """
        # Placeholder: return minimal body
        # The actual body contains:
        #  - Magic: 0xACED (Java serialization stream magic)
        #  - Version: 0x0005
        #  - TC_OBJECT with encrypted fields
        # For now, return empty — callers should use cached credentials
        return b""


def load_cached_devices(filepath: str) -> List[DeviceInfo]:
    """
    Load cached device information from a JSON file.

    This is useful when you've already retrieved credentials via the app
    or MITM proxy and want to control devices offline.

    Args:
        filepath: Path to JSON file

    Returns:
        List of DeviceInfo objects
    """
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


def save_cached_devices(devices: List[DeviceInfo], filepath: str):
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
