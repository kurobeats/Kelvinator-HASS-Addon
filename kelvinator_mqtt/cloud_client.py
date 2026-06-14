"""
Kelvinator / Electrolux BroadLink Cloud API Client.

Based on reverse-engineered protocol from com.kelvinator.airconditioner v3.8.2.
Cloud provider: BroadLink (Hangzhou BroadLink Technology Co., Ltd.)

Implements the account login and device management HTTP layer.
The device control layer goes through the BroadLink native DNA protocol.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — extracted from decompiled source
# ---------------------------------------------------------------------------

_AES_IV = bytes(
    [0xEA, 0xAA, 0xAA, 0x3A, 0xBB, 0x58, 0x62, 0xA2,
     0x19, 0x18, 0xB5, 0x77, 0x1D, 0x16, 0x15, 0xAA]
)
_TOKEN_SALT = "xgx3d*fe3478$ukx"
_TIMESTAMP_SALT = "kdixkdqp54545^#*"
_PASSWORD_SALT = "4969fj#k23#"

# Key permutation table from BLCommonTools.aeskeyDecrypt()
_KEY_PERMUTATION = [7, 12, 3, 0, 11, 15, 2, 4, 5, 9, 14, 1, 13, 10, 8, 6]

# The licenseId is derived at runtime after SDK init.
# We use a fixed licenseId from the app binary as fallback.
_DEFAULT_LICENSE_ID = "bddb4af53f74edaa03b1aa439b75e7a6"

# ---------------------------------------------------------------------------
# Cryptographic helpers — matching BLCommonTools implementations
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
    """Convert hex string to bytes, matching parseStringToByte()."""
    return bytes.fromhex(hex_str)


def _permute_key(md5_hex: str) -> bytes:
    """Apply the key permutation from aeskeyDecrypt()."""
    md5_bytes = _parse_hex_to_bytes(md5_hex)
    key = bytearray(16)
    for i, idx in enumerate(_KEY_PERMUTATION):
        key[i] = md5_bytes[idx]
    return bytes(key)


def _encrypt_body(plaintext: str, timestamp: str) -> str:
    """
    Encrypt the request body with AES/CBC/ZeroBytePadding.

    Matches BLCommonTools.aesNoPadding() which does:
      1. key = MD5(timestamp + "kdixkdqp54545^#*") → parse hex → permute
      2. AES/CBC/ZeroBytePadding with hardcoded IV
      3. Return hex-encoded ciphertext
    """
    md5_key_hex = _md5(timestamp + _TIMESTAMP_SALT)
    aes_key = _permute_key(md5_key_hex)

    # Zero-byte padding to block size
    data = plaintext.encode("utf-8")
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=_AES_IV)
    padded = pad(data, AES.block_size)
    ciphertext = cipher.encrypt(padded)
    return ciphertext.hex()


def _make_token(plaintext: str) -> str:
    """Calculate the token header: MD5(body + 'xgx3d*fe3478$ukx')."""
    return _md5(plaintext + _TOKEN_SALT)


def _hash_password(raw_password: str) -> str:
    """Hash password: SHA1(SHA256(raw) + '4969fj#k23#')."""
    return _sha1(_sha256(raw_password) + _PASSWORD_SALT)


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------


class BroadLinkCloudClient:
    """Authenticated client for the BroadLink cloud API."""

    BASE_ACCOUNT: str = "https://{}bizaccount.ibroadlink.com"
    BASE_FAMILY: str = "https://{}bizihcv0.ibroadlink.com"
    BASE_APP_MANAGE: str = "https://{}bizappmanage.ibroadlink.com"
    BASE_ELECTROLUX: str = "https://{}thirdpartyservice.ibroadlink.com"

    def __init__(
        self,
        license_id: str = _DEFAULT_LICENSE_ID,
        timeout: int = 15,
    ) -> None:
        self._license_id = license_id
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "text/plain;charset=utf-8",
            "system": "android",
            "appPlatform": "android",
            "appVersion": "3.8.2",
        })

        # Auth state
        self._userid: Optional[str] = None
        self._loginsession: Optional[str] = None
        self._companyid: Optional[str] = None
        self._nickname: Optional[str] = None
        self._account: Optional[str] = None

    # -------------------------------------------------- Properties

    @property
    def userid(self) -> Optional[str]:
        return self._userid

    @property
    def is_logged_in(self) -> bool:
        return self._loginsession is not None

    # -------------------------------------------------- Internal HTTP

    def _account_url(self, path: str) -> str:
        return self.BASE_ACCOUNT.format(self._license_id) + path

    def _family_url(self, path: str) -> str:
        return self.BASE_FAMILY.format(self._license_id) + path

    def _electrolux_url(self, path: str) -> str:
        return self.BASE_ELECTROLUX.format(self._license_id) + path

    def _app_manage_url(self, path: str) -> str:
        return self.BASE_APP_MANAGE.format(self._license_id) + path

    def _encrypted_post(self, url: str, body: dict) -> requests.Response:
        """POST with AES-encrypted body and MD5 token header."""
        timestamp = str(int(time.time()))
        plaintext = json.dumps(body, separators=(",", ":"))
        ciphertext = _encrypt_body(plaintext, timestamp)
        token = _make_token(plaintext)

        headers = {
            "timestamp": timestamp,
            "token": token,
        }

        _LOGGER.debug("POST %s body=%s", url, plaintext)
        resp = self._session.post(
            url, data=ciphertext, headers=headers, timeout=self._timeout
        )
        _LOGGER.debug("Response [%d]: %s", resp.status_code, resp.text[:500])
        return resp

    # -------------------------------------------------- Auth

    def login(self, username: str, password: str) -> dict:
        """
        Authenticate with the BroadLink account service.

        Returns the full login result dict, or raises on failure.
        """
        body = {
            "password": _hash_password(password),
            "companyid": self._license_id,
        }

        if "@" in username:
            body["email"] = username
        else:
            body["phone"] = username

        # The account API login uses AES-encrypted body
        # But also supports JSON POST depending on endpoint
        timestamp = str(int(time.time()))
        plaintext = json.dumps(body, separators=(",", ":"))

        try:
            resp = self._encrypted_post(
                self._account_url("/account/login"), body
            )
        except requests.RequestException as exc:
            _LOGGER.error("Login request failed: %s", exc)
            raise

        result = resp.json()
        if result.get("error") != 0:
            msg = result.get("message", "Unknown error")
            raise RuntimeError(f"Login failed: {msg} (code={result.get('error')})")

        self._userid = result.get("userid")
        self._loginsession = result.get("loginsession")
        self._companyid = result.get("companyid")
        self._nickname = result.get("nickname")
        self._account = username

        _LOGGER.info("Logged in as %s (uid=%s)", self._nickname, self._userid)
        return result

    # -------------------------------------------------- Timestamp

    def get_server_timestamp(self) -> dict:
        """Get server time — used for token/key derivation."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/common/api"), {}
        )
        return resp.json()

    # -------------------------------------------------- Family / Device List

    def get_family_id_list(self) -> dict:
        """Get all family IDs for this account."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/user/getfamilyid"),
            {"userid": self._userid or ""},
        )
        return resp.json()

    def get_family_all_info(self, family_id: str) -> dict:
        """Get all family info including devices."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/family/getallinfo"),
            {"familyid": family_id},
        )
        return resp.json()

    def get_family_base_info_list(self) -> dict:
        """Get base info for all families."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/user/getbasefamilylist"),
            {"userid": self._userid or ""},
        )
        return resp.json()

    # -------------------------------------------------- Device Management

    def get_device_family(self, did: str) -> dict:
        """Get the family a device belongs to."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/dev/getfamily"),
            {"did": did},
        )
        return resp.json()

    def delete_device(self, did: str, family_id: str) -> dict:
        """Delete/remove a device."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/dev/deldev"),
            {"did": did, "familyid": family_id},
        )
        return resp.json()

    def rename_device(self, did: str, name: str) -> dict:
        """Rename a device module."""
        resp = self._encrypted_post(
            self._family_url("/ec4/v1/module/modifyname"),
            {"did": did, "name": name},
        )
        return resp.json()

    # -------------------------------------------------- Electrolux-specific

    def get_model_number_list(self) -> dict:
        """Get available model numbers for device setup."""
        resp = self._encrypted_post(
            self._electrolux_url("/thirdparty/v1/dev/getmodelnumberlist"),
            {},
        )
        return resp.json()

    def get_device_hardware_info(self, sn: str) -> dict:
        """Get device hardware info by serial number."""
        resp = self._encrypted_post(
            self._electrolux_url("/thirdparty/v1/dev/getdevhwinfo"),
            {"sn": sn},
        )
        return resp.json()

    def get_device_pid(self, sn: str) -> dict:
        """Get product ID for a device."""
        resp = self._encrypted_post(
            self._electrolux_url("/thirdparty/v1/dev/getdevtype"),
            {"sn": sn},
        )
        return resp.json()

    # -------------------------------------------------- Timers

    def add_timer(self, did: str, timer_data: dict) -> dict:
        """Add a timer task."""
        body = {"did": did, **timer_data}
        resp = self._encrypted_post(
            self._electrolux_url("/thirdparty/v1/timetask/manage/add"),
            body,
        )
        return resp.json()

    def query_timers(self, did: str) -> dict:
        """Query timer tasks for a device."""
        resp = self._encrypted_post(
            self._electrolux_url("/thirdparty/v1/timetask/query"),
            {"did": did},
        )
        return resp.json()

    def delete_timer(self, did: str, task_id: str) -> dict:
        """Delete a timer task."""
        resp = self._encrypted_post(
            self._electrolux_url("/thirdparty/v1/timetask/manage/del"),
            {"did": did, "id": task_id},
        )
        return resp.json()

    # -------------------------------------------------- Convenience

    def close(self) -> None:
        self._session.close()
