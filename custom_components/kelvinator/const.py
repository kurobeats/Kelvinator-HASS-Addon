"""Constants for the Kelvinator Home Comfort integration."""

from enum import IntEnum

# ---------------------------------------------------------------------------
# Integration metadata
# ---------------------------------------------------------------------------

DOMAIN = "kelvinator"
PLATFORMS = ["climate", "switch", "sensor"]
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_COUNTRY_CODE = "country_code"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_POLL_INTERVAL = 30
DEFAULT_COUNTRY_CODE = "61"

# ---------------------------------------------------------------------------
# BroadLink cloud constants (from decompiled app)
# ---------------------------------------------------------------------------

AES_IV = bytes(
    [0xEA, 0xAA, 0xAA, 0x3A, 0xBB, 0x58, 0x62, 0xA2,
     0x19, 0x18, 0xB5, 0x77, 0x1D, 0x16, 0x15, 0xAA]
)
TOKEN_SALT = "xgx3d*fe3478$ukx"
TIMESTAMP_SALT = "kdixkdqp54545^#*"
PASSWORD_SALT = "4969fj#k23#"
DEFAULT_LICENSE_ID = "bddb4af53f74edaa03b1aa439b75e7a6"

# Full base64 License from AirApplication.java — bytes 120:136 = companyid
FULL_LICENSE = (
    "vdtK9T907aoDsapDm3Xnpviv67CfTNVaCnBaVHLbiTo0j+/RvjQpBrWd6wi3wqkc"
    "5OkMWgAAAACYJzsfBji8eBl5PVjaBV0221pCDlvjSasStCYcZJK9YB8Ze5skOd3JxQ"
    "artvnM1yncOPqd/5kKHxJ0Y7b4U5AFg/vh4BVg6qjaYHnfiJKkvAAAAAA="
)
import base64
COMPANY_ID = base64.b64decode(FULL_LICENSE)[120:136].hex()

# ---------------------------------------------------------------------------
# Kelvinator AC mode constants (from ACCommonUtils.java)
# ---------------------------------------------------------------------------


class AcMode(IntEnum):
    COOL = 0
    HEAT = 1
    DRY = 2
    FAN_ONLY = 3
    AUTO = 4
    ECO = 5
    EIGHT_HEAT = 6
    TWELVE_HEAT = 7


class FanSpeed(IntEnum):
    AUTO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    TURBO = 4
    QUIET = 5
    LOW_MED = 6
    MED_HIGH = 7


# ---------------------------------------------------------------------------
# Maps: Kelvinator ↔ HA
# ---------------------------------------------------------------------------

MODE_KELVINATOR_TO_HA = {
    AcMode.COOL: "cool",
    AcMode.HEAT: "heat",
    AcMode.DRY: "dry",
    AcMode.FAN_ONLY: "fan_only",
    AcMode.AUTO: "auto",
    AcMode.ECO: "cool",      # ECO is treated as cool with energy saving
    AcMode.EIGHT_HEAT: "heat",
    AcMode.TWELVE_HEAT: "heat",
}

MODE_HA_TO_KELVINATOR = {
    "cool": AcMode.COOL,
    "heat": AcMode.HEAT,
    "dry": AcMode.DRY,
    "fan_only": AcMode.FAN_ONLY,
    "auto": AcMode.AUTO,
}

FAN_KELVINATOR_TO_HA = {
    FanSpeed.AUTO: "auto",
    FanSpeed.LOW: "low",
    FanSpeed.MEDIUM: "medium",
    FanSpeed.HIGH: "high",
    FanSpeed.TURBO: "high",
    FanSpeed.QUIET: "low",
    FanSpeed.LOW_MED: "medium",
    FanSpeed.MED_HIGH: "medium",
}

FAN_HA_TO_KELVINATOR = {
    "auto": FanSpeed.AUTO,
    "low": FanSpeed.LOW,
    "medium": FanSpeed.MEDIUM,
    "high": FanSpeed.HIGH,
}

SWING_MODES = ["off", "vertical", "horizontal", "both"]
FAN_MODES = ["auto", "low", "medium", "high"]
HVAC_MODES = ["off", "cool", "heat", "dry", "fan_only", "auto"]
