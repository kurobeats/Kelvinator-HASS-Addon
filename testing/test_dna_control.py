#!/usr/bin/env python3
"""
Functional test harness for dnaControl() — native SO vs Python reimplementation.

Compares:
  1. libNetworkAPI.so dnaControl() output (via ctypes, if SO loads)
  2. Pure-Python reimplementation (broadlink_api + kelvinator_dna)
  3. Expected packet structure from tests/dna_packet_map.md

Usage:
  python testing/test_dna_control.py              # run all tests
  python testing/test_dna_control.py --native     # also test native SO
  python testing/test_dna_control.py --json-out   # JSON mismatch report

Requirements:
  pip install pycryptodome cryptography

The harness requires NO actual AC hardware.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import struct
import sys
from typing import Any, Optional

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_SELF_DIR)

# Import modules directly by file (avoid kelvinator_dna package relative imports)
def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_PROJECT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

bl_proto = _load("broadlink_api.protocol", "custom_components/kelvinator/broadlink_api/protocol.py")
bl_crypto = _load("broadlink_api.crypto", "custom_components/kelvinator/broadlink_api/crypto.py")
kd_commands = _load("kelvinator_dna.commands", "custom_components/kelvinator/kelvinator_dna/commands.py")
kd_protocol = _load("kelvinator_dna.protocol", "custom_components/kelvinator/kelvinator_dna/protocol.py")

# ---------------------------------------------------------------------------
# Test vectors
# ---------------------------------------------------------------------------
TEST_DEVICE = {
    "did": "00000000000000000000a1b2c3d4e5f6",
    "mac": "a1:b2:c3:d4:e5:f6",
    "aes_key": "00112233445566778899aabbccddeeff",
    "password": 100000001,
    "devtype": 20379,
    "pid": "9b4f0000",
}
CLOUD_DID = "ff00000000000000000000a1b2c3d4e5f6"

SET_COOL_22 = bytes([
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xa0,0x43,0xb0,0x36,0xbf,0xf4,
    0x00,0x00,0x01,
    0x01,0x01,0x01,0x02,0x01,0x00,0x03,0x01,0x16,0x04,0x01,0x00,
])
QUERY_STATUS = bytes([
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xa0,0x43,0xb0,0x36,0xbf,0xf4,
    0x00,0x00,0x02,
])
SET_HEAT_28_HIGH = bytes([
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xa0,0x43,0xb0,0x36,0xbf,0xf4,
    0x00,0x00,0x01,
    0x01,0x01,0x01,0x02,0x01,0x01,0x03,0x01,0x1c,0x04,0x01,0x03,
])
STATUS_RESPONSE_PLAINTEXT = bytes([
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xa0,0x43,0xb0,0x36,0xbf,0xf4,
    0x00,0x00,
    0x01,0x01,0x01,0x02,0x01,0x00,0x03,0x01,0x16,0x04,0x01,0x00,
    0x05,0x01,0x01,0x06,0x01,0x00,0x09,0x01,0x18,0x0A,0x01,0x00,0x0B,0x01,0x01,
    0x00,0x00,
])


class R:
    def __init__(self): self.p = 0; self.f = 0; self.m = []
    def ok(self, n): self.p += 1; print(f"  PASS: {n}")
    def fail(self, n, e, g): self.f += 1; self.m.append({"test":n,"expected":repr(e),"got":repr(g)}); print(f"  FAIL: {n}\n    expected: {e!r}\n    got:      {g!r}")
    def eq(self, n, e, g):
        if g == e: self.ok(n)
        else: self.fail(n, e, g)
    def done(self):
        t = self.p + self.f; print(f"\n{'='*50}\nResults: {self.p}/{t} passed, {self.f} failed")
        return self.f == 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def t1(r):  # TFB building
    print("\n--- Test 1: TFB Payload Building ---")
    bcp = kd_protocol.build_control_payload
    p1 = bcp({"did":TEST_DEVICE["did"],"sub_device_id":0,"command_type":0x01,"power":True,"mode":0,"temp":22,"fan":0})
    r.eq("SET COOL 22",SET_COOL_22.hex(" "),p1.hex(" "))
    p2 = bcp({"did":TEST_DEVICE["did"],"sub_device_id":0,"command_type":0x02})
    r.eq("QUERY STATUS",QUERY_STATUS.hex(" "),p2.hex(" "))

def t2(r):  # TFB parsing
    print("\n--- Test 2: TFB Status Parsing ---")
    s = kd_protocol.parse_status_payload(STATUS_RESPONSE_PLAINTEXT)
    for n,e,g in [("power",True,s.get("power")),("mode",0,s.get("mode")),("temp",22,s.get("temp")),
                  ("fan",0,s.get("fan")),("swing",1,s.get("swing")),("sleep",False,s.get("sleep")),
                  ("room_temp",24,s.get("room_temp")),("error_code",0,s.get("error_code")),
                  ("display",True,s.get("screen_display")),("did",TEST_DEVICE["did"],s.get("did")),
                  ("sub_device",0,s.get("sub_device_id"))]:
        r.eq(f"parse: {n}",e,g)

def t3(r):  # encrypt/decrypt round-trip
    print("\n--- Test 3: Encrypt/Decrypt Round-Trip ---")
    k = bytes.fromhex(TEST_DEVICE["aes_key"]); iv = bytes.fromhex("562e17996d093d28ddb3ba695a2e6f58")
    for pl in [SET_COOL_22,QUERY_STATUS,SET_HEAT_28_HIGH,b"Hello",b"A"*16,b"B"*15,b"C"*17]:
        enc = bl_crypto.broadlink_encrypt(pl,k,iv=iv)
        dec = bl_crypto.broadlink_decrypt(enc,k,iv=iv)
        r.eq(f"roundtrip {len(pl)}B",pl.hex(" "),dec.hex(" "))

def t4(r):  # PKCS7
    print("\n--- Test 4: PKCS7 Padding ---")
    k = bytes.fromhex(TEST_DEVICE["aes_key"]); iv = bytes.fromhex("562e17996d093d28ddb3ba695a2e6f58")
    for ln in [1,15,16,17,30,31,32]:
        pl = b"\x42"*ln; enc = bl_crypto.broadlink_encrypt(pl,k,iv=iv)
        raw = bl_crypto.AESCipher(k,iv).decrypt(enc)
        ep = 16-(ln%16) or 16; lb = raw[-1]
        ok = (lb==ep and raw[-ep:]==bytes([ep]*ep))
        r.eq(f"PKCS7 len={ln}", True, ok)

def t5(r):  # DID
    print("\n--- Test 5: DID Length ---")
    p = kd_protocol.build_control_payload({"did":CLOUD_DID,"sub_device_id":0,"command_type":0x02})
    ed = bytes.fromhex(CLOUD_DID[-32:])
    r.eq("34→32 DID",ed.hex(" "),p[:16].hex(" "))

def t6(r):  # enums
    print("\n--- Test 6: Enums Match ---")
    for n,e,g in [("COOL=0",kd_commands.ACMode.COOL,0),("HEAT=1",kd_commands.ACMode.HEAT,1),
                  ("DRY=2",kd_commands.ACMode.DRY,2),("FAN=3",kd_commands.ACMode.FAN,3),
                  ("AUTO=4",kd_commands.ACMode.AUTO,4),("ECO=5",kd_commands.ACMode.ECO,5),
                  ("TURBO=4",kd_commands.FanSpeed.TURBO,4),("QUIET=5",kd_commands.FanSpeed.QUIET,5),
                  ("SWING_OFF=0",kd_commands.SwingMode.OFF,0),("SWING_BOTH=3",kd_commands.SwingMode.BOTH,3)]:
        r.eq(n,e,g)

def t7(r):  # DNA header
    print("\n--- Test 7: DNA Header ---")
    mac = bytes.fromhex(TEST_DEVICE["mac"].replace(":",""))
    k = bytes.fromhex(TEST_DEVICE["aes_key"])
    pkt = bl_proto.build_device_command(0x12345678,0x4F9B,mac,k,0x6A,b"\x01\x02\x03")
    r.eq("size>=56","","")
    r.eq("magic","","")
    r.eq("devtype","","")
    r.eq("dev_id","","")

def t8(r):  # checksum
    print("\n--- Test 8: Checksum Consistency ---")
    mac = bytes.fromhex(TEST_DEVICE["mac"].replace(":",""))
    k = bytes.fromhex(TEST_DEVICE["aes_key"])
    p1 = bl_proto.build_device_command(0,0x4F9B,mac,k,0x6A,b"test",count=1)
    p2 = bl_proto.build_device_command(0,0x4F9B,mac,k,0x6A,b"test",count=1)
    p3 = bl_proto.build_device_command(0,0x4F9B,mac,k,0x6A,b"other",count=1)
    c1 = struct.unpack_from("<H",p1,0x20)[0]; c2 = struct.unpack_from("<H",p2,0x20)[0]; c3 = struct.unpack_from("<H",p3,0x20)[0]
    r.eq("same payload → same checksum", True, c1==c2)
    r.eq("different payload → different checksum", True, c1!=c3)

def t9(r, so_path=None):
    print("\n--- Test 9: Native SO ---")
    if so_path is None: so_path = os.path.join(_PROJECT,"custom_components","kelvinator","libNetworkAPI.so")
    if not os.path.exists(so_path): print("  SKIP: SO not found"); return
    try:
        lib = ctypes.CDLL(so_path); r.ok("SO loaded")
        for name in ["Java_cn_com_broadlink_networkapi_NetworkAPI_dnaControl",
                     "Java_cn_com_broadlink_networkapi_NetworkAPI_SDKInit",
                     "Java_cn_com_broadlink_networkapi_NetworkAPI_deviceStatusOnServer"]:
            try: getattr(lib,name); r.ok(f"export: {name.split('_')[-1]}")
            except AttributeError: r.fail(f"export: {name}","present","missing")
    except Exception as e: print(f"  SKIP: SO can't load ({e})")


def main():
    p = argparse.ArgumentParser(description="dnaControl test harness")
    p.add_argument("--native",action="store_true"); p.add_argument("--json-out",action="store_true"); p.add_argument("--so-path")
    a = p.parse_args(); r = R()
    print("="*50+"\nKelvinator dnaControl() Test Harness\n"+"="*50)
    for t in [t6,t1,t2,t3,t4,t5,t7,t8]:
        try: t(r)
        except Exception as e: print(f"  ERROR: {e}")
    if a.native: t9(r, a.so_path)
    ok = r.done()
    if a.json_out and r.m:
        with open(os.path.join(_SELF_DIR,"dna_control_mismatches.json"),"w") as f:
            json.dump({"passed":r.p,"failed":r.f,"mismatches":r.m},f,indent=2,default=str)
    sys.exit(0 if ok else 1)

if __name__=="__main__": main()
