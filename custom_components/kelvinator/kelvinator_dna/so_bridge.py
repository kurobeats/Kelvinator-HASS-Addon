"""
SO Bridge: ctypes-based interface to call libNetworkAPI.so directly.

This module allows calling the native BroadLink library functions from Python
using ctypes. This bypasses the need to reimplement encryption, but requires
the .so file from the APK (arm64-v8a or armeabi-v7a).

Usage:
    from kelvinator_dna.so_bridge import NetworkAPI

    api = NetworkAPI("/path/to/libNetworkAPI.so")
    api.sdk_init()
    result = api.dna_control(did, mac, aes_key, password, command_json)

WARNING: This approach depends on the compiled .so which is a proprietary
binary. Use the pure Python implementation (kelvinator_dna.protocol) for a fully
open-source solution.
"""

import ctypes
import json
import os
import platform
from typing import Optional
from ctypes import c_char_p, c_int, c_void_p, POINTER


class _JNIEnv(ctypes.Structure):
    """Minimal JNIEnv stub — not actually used, just for type completeness."""
    pass


class NetworkAPI:
    """
    Python wrapper for libNetworkAPI.so using ctypes.

    Maps the JNI native methods to Python-callable functions.
    """

    # Function signatures based on JNI exports found in Ghidra
    _JNI_FUNCTIONS = {
        "Java_cn_com_broadlink_networkapi_NetworkAPI_SDKInit":
            ([c_void_p, c_void_p, c_char_p], c_int),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_dnaControl":
            ([c_void_p, c_void_p, c_char_p, c_char_p, c_char_p, c_char_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_devicePair":
            ([c_void_p, c_void_p, c_char_p, c_char_p], c_int),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceProbe":
            ([c_void_p, c_void_p, c_char_p, c_char_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceStatusOnServer":
            ([c_void_p, c_void_p, c_char_p, c_char_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceSubControl":
            ([c_void_p, c_void_p, c_char_p, c_char_p, c_char_p, c_char_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceSubControlTranslate":
            ([c_void_p, c_void_p, c_char_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceBindWithServer":
            ([c_void_p, c_void_p, c_char_p], c_int),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceProfile":
            ([c_void_p, c_void_p, c_char_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_LicenseInfo":
            ([c_void_p, c_void_p], c_char_p),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_setNetworkCallback":
            ([c_void_p, c_void_p, c_void_p], c_int),
        "Java_cn_com_broadlink_networkapi_NetworkAPI_setDeviceControlCallback":
            ([c_void_p, c_void_p, c_void_p], c_int),
    }

    def __init__(self, lib_path: str):
        """
        Load the native library.

        Args:
            lib_path: Path to libNetworkAPI.so
        """
        if not os.path.exists(lib_path):
            raise FileNotFoundError(f"Library not found: {lib_path}")

        self._lib = ctypes.CDLL(lib_path)
        self._initialized = False
        self._setup_functions()

    def _setup_functions(self):
        """Configure ctypes function signatures for all JNI exports."""
        for name, (argtypes, restype) in self._JNI_FUNCTIONS.items():
            try:
                func = getattr(self._lib, name)
                func.argtypes = argtypes
                func.restype = restype
            except AttributeError:
                pass  # Function not exported (may be stripped)

    def sdk_init(self, config_json: str = "{}") -> int:
        """
        Initialize the SDK.

        Args:
            config_json: JSON configuration string

        Returns:
            0 on success, non-zero on error
        """
        func = self._lib.Java_cn_com_broadlink_networkapi_NetworkAPI_SDKInit
        result = func(
            c_void_p(0),          # JNIEnv* (not used by the native code)
            c_void_p(0),          # jclass (not used)
            config_json.encode('utf-8'),
        )
        if result == 0:
            self._initialized = True
        return result

    def dna_control(
        self,
        dev_info: str,
        sub_dev_info: str,
        data: str,
        cmd_desc: str,
    ) -> str:
        """
        Send a DNA control command to the device.

        This is the main function used by the app for device control.

        Matches the JNI signature from the decompiled app:
          NetworkAPI.dnaControl(String devInfo, String subDevInfo,
                                String data, String cmdDesc)

        Args:
            dev_info: JSON device info (DID, MAC, etc.)
            sub_dev_info: JSON sub-device info or empty string
            data: JSON control command parameters
            cmd_desc: Command type identifier (e.g. "dev_ctrl")

        Returns:
            JSON response string
        """
        func = self._lib.Java_cn_com_broadlink_networkapi_NetworkAPI_dnaControl
        result = func(
            c_void_p(0),          # JNIEnv*
            c_void_p(0),          # jclass
            dev_info.encode('utf-8'),
            sub_dev_info.encode('utf-8'),
            data.encode('utf-8'),
            cmd_desc.encode('utf-8'),
        )
        # Result is a jstring — ctypes returns a char* for us
        if result:
            return result.decode('utf-8')
        return ""

    def device_probe(self, did: str, mac: str) -> str:
        """
        Probe for a device on the local network.

        Returns:
            JSON with device information
        """
        func = self._lib.Java_cn_com_broadlink_networkapi_NetworkAPI_deviceProbe
        result = func(
            c_void_p(0), c_void_p(0),
            did.encode('utf-8'),
            mac.encode('utf-8'),
        )
        if result:
            return result.decode('utf-8')
        return ""

    def license_info(self) -> str:
        """Get license information."""
        func = self._lib.Java_cn_com_broadlink_networkapi_NetworkAPI_LicenseInfo
        result = func(c_void_p(0), c_void_p(0))
        if result:
            return result.decode('utf-8')
        return ""

    def device_status_on_server(self, config: str, did: str = "") -> str:
        """Get device status via cloud server.

        Matches JNI signature: deviceStatusOnServer(String config, String did)
        """
        func = self._lib.Java_cn_com_broadlink_networkapi_NetworkAPI_deviceStatusOnServer
        result = func(c_void_p(0), c_void_p(0), config.encode('utf-8'), did.encode('utf-8'))
        if result:
            return result.decode('utf-8')
        return ""


def find_library() -> Optional[str]:
    """
    Attempt to find libNetworkAPI.so on the system.

    Returns:
        Path to the library, or None if not found
    """
    search_paths = [
        os.path.expanduser("~/Downloads/libNetworkAPI.so"),
        "/usr/local/lib/libNetworkAPI.so",
        "./libNetworkAPI.so",
        "../libNetworkAPI.so",
    ]
    for path in search_paths:
        if os.path.exists(path):
            return path
    return None
