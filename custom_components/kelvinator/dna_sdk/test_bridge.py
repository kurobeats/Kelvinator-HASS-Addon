#!/usr/bin/env python3
"""Self-check for dna_bridge. Run from dna_sdk dir: python3 test_bridge.py"""
import json, os, subprocess, sys

DIR = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ)
env["LD_LIBRARY_PATH"] = DIR
env["LD_PRELOAD"] = os.path.join(DIR, "shim_internal.so")

proc = subprocess.Popen(
    [sys.executable, "-u", os.path.join(DIR, "dna_bridge.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
)

def rpc(op, **kw):
    kw["op"] = op
    proc.stdin.write((json.dumps(kw) + "\n").encode()); proc.stdin.flush()
    return json.loads(proc.stdout.readline())

r = rpc("init", config={"license": "bddb4af53f74edaa03b1aa439b75e7a6",
                        "packageName": "com.kelvinator.airconditioner",
                        "loglevel": 4, "filepath": os.path.join(DIR, "scripts")})
assert r["ok"] and '"status":0' in r["resp"], r
print("init OK:", r["resp"])

# Example device values — replace with your own via env or edit.
# NOTE: packet build works with any DID/MAC; the query only succeeds against
# a real device you own.
DID = os.environ.get("KELVINATOR_TEST_DID", "00000000000000000000a1b2c3d4e5f6")
dev = {"did": DID, "mac": "a1:b2:c3:d4:e5:f6",
       "aes_key": "00112233445566778899aabbccddeeff", "password": 0,
       "pid": "9b4f0000", "devtype": 20379, "magiccode": "9b4f0000",
       "ip": "192.168.1.101", "port": 80}
sub = {"did": DID, "pid": "9b4f0000",
       "name": "AC 1"}
params = ["ac_pwr", "ac_mode", "temp", "ac_mark", "ac_vdir", "ac_slp",
          "scrdisp", "ecomode", "envtemp", "ac_errcode"]
data = {"act": "get", "params": params, "vals": [[{"val": 0}] for _ in params]}
desc = {"name": "dev_data", "command": "dev_data", "cookie": "aabb"}
r = rpc("ctrl", dev=dev, sub=sub, data=data, desc=desc)
assert r["ok"], r
import base64
pkt = base64.b64decode(json.loads(r["resp"])["data"]["ctrldata"])
assert pkt[:4] == b"\xa5\xa5\x5a\x5a", pkt[:8].hex()
# payload checksum at [4:6], seed 0xbeaf over packet with [4:6] zeroed
ck = (sum(pkt) - pkt[4] - pkt[5] + 0xBEAF + 0xBEAF) & 0xFFFF
# careful: zero out 4,5 then sum with seed
z = bytearray(pkt); z[4] = 0; z[5] = 0
ck = (sum(z, 0xBEAF)) & 0xFFFF
assert ck == pkt[4] | (pkt[5] << 8), (hex(ck), hex(pkt[4] | (pkt[5] << 8)))
assert pkt[6] == 0x01 and pkt[7] == 0x0b
body = json.loads(pkt[12:])
assert body["did"] == DID and "ac_pwr" in body
print("dev_data packet OK:", pkt[:12].hex(), json.dumps(body)[:80])
proc.stdin.close(); proc.wait()
print("ALL BRIDGE CHECKS PASSED")
