"""
Kelvinator AC protocol: DNA Kit payload serialization.

Ground truth: the decrypted DNA Kit Lua script
(`9b4f0000000000000000000000000000.script`, shipped with the official app)
plus live output of the bundled DNA SDK.  The wire payload is NOT the
TFB [did][sub][cmd][params] format guessed at earlier — it is a fixed
12-byte header followed by a JSON body whose keys are the DNA Kit
parameter NAMES (strings like "ac_pwr"), values inline.

Payload layout (plaintext, before AES encryption):

  [0:4]   a5 a5 5a 5a          magic
  [4:6]   checksum (LE)        sum(bytes) with [4:6] zeroed, seed 0xBEAF
  [6]     0x01 = get (query), 0x02 = set (control)
  [7]     0x0b                 protocol tag (constant, from DNA Kit)
  [8:10]  body length (LE)
  [10:12] version (LE)         0
  [12:]   JSON body

Request body:  {"<param>": <val>, ..., "did": "<subdevice did>"}
Response body: {"did": "...", "<param>": <val>, ...}   (values inline)

Known parameter names (from the DNA Kit script `g_func` table):
  ac_pwr, ac_mode, temp, ac_mark, ac_vdir, ac_hdir, ac_slp, scrdisp,
  ecomode, qtmode, envtemp (RO), ac_errcode (RO), tempunit, anionmode,
  drmode, drtime, espmode, filreset, insectrepellent, mldprf, timer,
  ac_timingtime, modelnumber, sn, ac_coldplasma, ac_compressorstatus (RO),
  ac_evapordefroststate (RO), ac_fourwayvalvestatus (RO),
  ac_heaterstatus (RO), ac_indoorfanstatus (RO), ac_setsleepinfan,
  ac_setmarkindehum, ac_setecoindehum, ac_setquietinallmode,
  ac_setautomarkinauto, ac_setautomarkinfan, ac_setmarkinauto,
  ac_setecoinauto, ac_settempindehum, upload_enable
"""

import json
from typing import Any

MAGIC = b"\xa5\xa5\x5a\x5a"
ACT_GET = 0x01
ACT_SET = 0x02
PROTO_TAG = 0x0B
CHECKSUM_SEED = 0xBEAF

# DNA Kit function table (order matters for response parsing in the SDK;
# here we only need the names).
DNA_KIT_PARAMS = [
    "envtemp", "anionmode", "disimode", "ecomode", "qtmode", "filreset",
    "tempunit", "espmode", "scrdisp", "mldprf", "ac_slp", "ac_vdir",
    "ac_hdir", "ac_mark", "temp", "ac_mode", "sn", "ac_pwr", "timer",
    "ac_timingtime", "modelnumber", "ac_errcode", "drmode", "drtime",
    "ac_coldplasma", "ac_compressorstatus", "ac_evapordefroststate",
    "ac_fourwayvalvestatus", "ac_heaterstatus", "ac_indoorfanstatus",
    "ac_setsleepinfan", "ac_setmarkindehum", "ac_setecoindehum",
    "ac_setquietinallmode", "ac_setautomarkinauto", "ac_setautomarkinfan",
    "ac_setmarkinauto", "ac_setecoinauto", "ac_settempindehum",
    "upload_enable",
]


def _checksum(data: bytes) -> int:
    """DNA Kit checksum: sum with seed 0xBEAF, checksum field zeroed."""
    zeroed = data[:4] + b"\x00\x00" + data[6:]
    return (sum(zeroed, CHECKSUM_SEED)) & 0xFFFF


def build_payload(
    did: str,
    act: str,
    params: dict[str, Any],
    version: int = 0,
) -> bytes:
    """
    Build a DNA Kit payload.

    did:   sub-device DID string (as used by the SDK; typically the
           full cloud DID, e.g. 34 chars).
    act:   "get" (query status) or "set" (control).
    params: {param_name: value} — values are ints/bools per DNA Kit.
    """
    body: dict[str, Any] = dict(params)
    body["did"] = did
    request = json.dumps(body, separators=(",", ":")).encode()

    cmd = bytearray(MAGIC)
    cmd.append(0)  # ck low placeholder
    cmd.append(0)  # ck high placeholder
    cmd.append(ACT_GET if act == "get" else ACT_SET)
    cmd.append(PROTO_TAG)
    cmd += len(request).to_bytes(2, "little")
    cmd += version.to_bytes(2, "little")
    cmd += request

    ck = _checksum(bytes(cmd))
    cmd[4] = ck & 0xFF
    cmd[5] = (ck >> 8) & 0xFF
    return bytes(cmd)


def parse_payload(data: bytes) -> dict[str, Any]:
    """
    Parse a DNA Kit response payload (decrypted).

    Verifies the checksum, returns the JSON body.  Raises ValueError on
    short/invalid data.
    """
    if len(data) < 12:
        raise ValueError(f"payload too short: {len(data)} bytes")
    ck = _checksum(bytes(data))
    if ck != data[4] | (data[5] << 8):
        raise ValueError(
            f"checksum mismatch: expected {data[4] | (data[5] << 8):#06x}, got {ck:#06x}"
        )
    length = data[8] | (data[9] << 8)
    body = data[12:12 + length]
    return json.loads(body.decode())


def parse_values(body: dict[str, Any]) -> dict[str, Any]:
    """Extract only DNA Kit param values (drop did/other keys)."""
    return {k: v for k, v in body.items() if k in DNA_KIT_PARAMS}


# ---------------------------------------------------------------------------
# Self-check: verify against the packet captured live from the DNA SDK
# (ctrldata for a status query; device identifiers redacted).
# ---------------------------------------------------------------------------

def _selfcheck() -> None:
    import base64
    # Live capture from libNetworkAPI.so (dnaControl dev_data, act=get),
    # with the device DID redacted (same length, checksum recomputed).
    # Structure, tag and checksum algorithm were verified byte-exact against
    # the SDK's real output.
    live = base64.b64decode(
        "paVaWsDUAQtKAAAAeyJhY19wd3IiOjAsImRpZCI6IjAwMDAwMDAwMDAwMDAwMDAwMDAwYTFi"
        "MmMzZDRlNWY2IiwiYWNfbW9kZSI6MCwidGVtcCI6MH0="
    )
    assert live[:4] == MAGIC
    parsed = parse_payload(live)
    assert parsed["ac_pwr"] == 0 and parsed["did"].endswith("a1b2c3d4e5f6")

    # rebuild and compare semantically (key order differs — cjson sorts)
    did = parsed["did"]
    rebuilt = build_payload(did, "get", {"ac_pwr": 0, "temp": 0, "ac_mode": 0})
    assert parse_payload(rebuilt) == parsed, (rebuilt.hex(), live.hex())
    print("protocol selfcheck OK")


if __name__ == "__main__":
    _selfcheck()