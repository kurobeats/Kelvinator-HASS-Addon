#!/usr/bin/env python3
"""
LAN device discovery + local UDP control test for Kelvinator AC units.

Usage:
  python testing/test_lan.py                        # interactive (prompts)
  python testing/test_lan.py --dry-run               # skip network, compile-check
  KELVINATOR_USER=0400000000 KELVINATOR_PASS=... \
    python testing/test_lan.py                        # non-interactive
  python testing/test_lan.py --ips 192.168.1.101     # specific IPs only

Failure diagnostics are printed inline. Each stage reports pass/fail + details.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import struct
import sys
import time
import traceback
from getpass import getpass

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_SELF_DIR)
sys.path.insert(0, os.path.join(_PROJECT, "custom_components", "kelvinator"))

# Import modules directly by file to avoid kelvinator_dna relative import issues
import importlib.util as _iu
def _load(name, rel):
    s = _iu.spec_from_file_location(name, os.path.join(_PROJECT, rel))
    m = _iu.module_from_spec(s); sys.modules[name] = m; s.loader.exec_module(m); return m

# Import order: register broadlink_api package first to avoid circular imports.
# broadlink_api/__init__.py imports everything → circular with submodules.
# Register an empty package, then load submodules into it.
_bapi = type(sys)("broadlink_api")
_bapi.__path__ = [os.path.join(_PROJECT, "custom_components", "kelvinator", "broadlink_api")]
sys.modules["broadlink_api"] = _bapi

bl_crypto = _load("broadlink_api.crypto", "custom_components/kelvinator/broadlink_api/crypto.py")
bl_proto = _load("broadlink_api.protocol", "custom_components/kelvinator/broadlink_api/protocol.py")
bl_dev = _load("broadlink_api.device", "custom_components/kelvinator/broadlink_api/device.py")
kd_proto = _load("kelvinator_dna.protocol", "custom_components/kelvinator/kelvinator_dna/protocol.py")
kd_cmds = _load("kelvinator_dna.commands", "custom_components/kelvinator/kelvinator_dna/commands.py")

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from const import PASSWORD_SALT, TIMESTAMP_SALT, TOKEN_SALT, COMPANY_ID, AES_IV, DEFAULT_LICENSE_ID

# ---------------------------------------------------------------------------
# Step 1: Cloud login
# ---------------------------------------------------------------------------

def cloud_login(username: str, password: str) -> tuple[str, str]:
    """Login to BroadLink cloud. Returns (userid, loginsession)."""
    import urllib.request, ssl

    ts = str(int(time.time()))
    pw_sha256 = hashlib.sha256((password + PASSWORD_SALT).encode()).hexdigest().lower()
    pw_hash = hashlib.sha1(pw_sha256.encode()).hexdigest().lower()

    body = json.dumps({
        "phone" if username.isdigit() else "email": username,
        "password": pw_hash,
        "companyid": COMPANY_ID,
    }, separators=(",", ":"))

    aes_key = bytes.fromhex(hashlib.md5((ts + TIMESTAMP_SALT).encode()).hexdigest().lower())
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=AES_IV)
    encrypted = cipher.encrypt(pad(body.encode(), AES.block_size))
    token = hashlib.md5(body.encode() + TOKEN_SALT.encode()).hexdigest().lower()

    url = f"https://{DEFAULT_LICENSE_ID}bizaccount.ibroadlink.com/account/login"
    req = urllib.request.Request(url, data=encrypted, headers={
        "Content-Type": "application/x-java-serialized-object",
        "system": "android", "appPlatform": "android",
        "language": "en-au", "timestamp": ts, "token": token,
    })

    ctx = ssl.create_default_context()
    print(f"  POST {url}")
    print(f"  ts={ts} token={token[:8]}... body={len(body)}B→{len(encrypted)}B")
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    err = data.get("error", -999)
    if err != 0:
        msg = data.get("msg", "unknown")
        raise RuntimeError(
            f"Login rejected: error={err} msg={msg}.\n"
            f"  Common causes:\n"
            f"  - -1005: AES key wrong (timestamp mismatch)\n"
            f"  - -1008: wrong password\n"
            f"  - -1036: rate-limited (wait and retry)\n"
        )
    return data["userid"], data["loginsession"]


# ---------------------------------------------------------------------------
# Step 2: Get device credentials
# ---------------------------------------------------------------------------

def cloud_get_devices(userid: str, loginsession: str) -> list[dict]:
    """Get device credentials from family API."""
    import urllib.request, ssl

    API_HOST = f"{DEFAULT_LICENSE_ID}bizihcv0.ibroadlink.com"
    ctx = ssl.create_default_context()

    # Get API key
    ts = str(int(time.time()))
    req = urllib.request.Request(f"https://{API_HOST}/ec4/v1/common/api", headers={
        "system": "android", "appPlatform": "android", "language": "en-au",
        "timestamp": ts, "Host": API_HOST,
    })
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        key_data = json.loads(resp.read().decode())
    api_key = key_data["key"]
    server_ts = key_data["timestamp"]
    server_key = bytes.fromhex(api_key)
    print(f"  API key obtained (server_ts={server_ts})")

    def enc(body_str):
        d = body_str.encode()
        padded = d + b'\x00' * (((len(d) // 16) + 2) * 16 - len(d))
        return AES.new(server_key, AES.MODE_CBC, iv=AES_IV).encrypt(padded)

    def tok(body_str):
        return hashlib.md5(
            (body_str + TOKEN_SALT + server_ts + userid).encode()
        ).hexdigest()

    def hdrs(body_str):
        return {
            "Content-type": "application/x-java-serialized-object",
            "system": "android", "appPlatform": "android", "language": "en-au",
            "loginsession": loginsession, "lid": DEFAULT_LICENSE_ID,
            "userid": userid, "timestamp": server_ts,
            "token": tok(body_str), "Host": API_HOST,
        }

    # Get family ID
    body2 = json.dumps({"userid": userid}, separators=(",", ":"))
    req2 = urllib.request.Request(f"https://{API_HOST}/ec4/v1/user/getfamilyid",
                                   data=enc(body2), headers=hdrs(body2))
    with urllib.request.urlopen(req2, context=ctx, timeout=15) as resp:
        fam = json.loads(resp.read().decode())
    fid = fam["familyinfo"][0]["id"]
    print(f"  Family ID: {fid[:8]}...")

    # Get all devices
    body3 = json.dumps({"userid": userid, "familyid": [fid]}, separators=(",", ":"))
    req3 = urllib.request.Request(f"https://{API_HOST}/ec4/v1/family/getallinfo",
                                   data=enc(body3), headers=hdrs(body3))
    with urllib.request.urlopen(req3, context=ctx, timeout=15) as resp:
        all_data = json.loads(resp.read().decode())

    family = all_data.get("familyallinfo", [{}])[0]
    result = []
    for dev in family.get("devinfo", []):
        result.append({
            "did": dev.get("did", ""), "mac": dev.get("mac", ""),
            "name": dev.get("name", ""), "aes_key": dev.get("aeskey", ""),
            "password": dev.get("password", 0),
            "devtype": dev.get("devtype", 20379), "pid": dev.get("pid", ""),
        })
    return result


# ---------------------------------------------------------------------------
# Step 3: LAN discovery
# ---------------------------------------------------------------------------

def lan_discover(timeout: float = 3.0) -> list[dict]:
    """Broadcast discovery on LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    pkt = bytearray(0x30)
    now = time.localtime()
    struct.pack_into("<HBBBBBB", pkt, 0x08,
                     now.tm_year, now.tm_sec, now.tm_min, now.tm_hour,
                     now.tm_wday + 1, now.tm_mday, now.tm_mon)
    pkt[0x26] = 0x06
    checksum = (sum(pkt, 0xBEAF)) & 0xFFFF
    struct.pack_into("<H", pkt, 0x20, checksum)

    sock.sendto(bytes(pkt), ("255.255.255.255", 80))
    print("  Broadcast sent (255.255.255.255:80)")

    devices = []
    start = time.time()
    while time.time() - start < timeout:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            break
        if len(data) < 0x40:
            continue
        devtype = struct.unpack_from("<H", data, 0x34)[0]
        mac_rev = data[0x3A:0x40]
        mac = bytes(reversed(mac_rev[:6]))
        mac_str = ":".join(f"{b:02x}" for b in mac)
        raw_name = data[0x40:].split(b"\x00")[0]
        try: name = raw_name.decode("utf-8")
        except UnicodeDecodeError: name = raw_name.decode("latin-1", errors="replace")
        devices.append({"ip": addr[0], "mac": mac_str, "devtype": devtype, "name": name})
        print(f"  Found: {name} @ {addr[0]} mac={mac_str} type=0x{devtype:04X}")
    sock.close()
    return devices


def direct_probe(ip: str, timeout: float = 1.5) -> str | None:
    """Probe a specific IP for MAC via discovery ping."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        pkt = bytearray(0x30)
        now = time.localtime()
        struct.pack_into("<HBBBBBB", pkt, 0x08,
                         now.tm_year, now.tm_sec, now.tm_min, now.tm_hour,
                         now.tm_wday + 1, now.tm_mday, now.tm_mon)
        pkt[0x26] = 0x06
        struct.pack_into("<H", pkt, 0x20, (sum(pkt, 0xBEAF)) & 0xFFFF)
        sock.sendto(bytes(pkt), (ip, 80))
        data, _ = sock.recvfrom(4096)
        sock.close()
        if len(data) >= 0x40:
            mac_rev = data[0x3A:0x40]
            mac = bytes(reversed(mac_rev[:6]))
            return ":".join(f"{b:02x}" for b in mac)
    except socket.timeout:
        pass
    except Exception as e:
        print(f"  Probe {ip}: error ({e})")
    return None


# ---------------------------------------------------------------------------
# Step 4: UDP auth + status
# ---------------------------------------------------------------------------

def udp_status(ip: str, mac_str: str, did: str, aes_key_hex: str, password: int) -> dict | None:
    """Auth + status query via local UDP."""
    BroadlinkDevice = bl_dev.BroadlinkDevice
    build_control_payload = kd_proto.build_control_payload
    parse_status_payload = kd_proto.parse_status_payload
    AC_DEVTYPE = kd_proto.AC_DEVTYPE

    mac_bytes = bytes.fromhex(mac_str.replace(":", ""))
    aes_key = bytes.fromhex(aes_key_hex)

    # DID: cloud returns 34 chars, wire protocol uses last 32
    did_hex = did[-32:] if len(did) > 32 else did
    print(f"  Connecting to {ip} (mac={mac_str}, did={did_hex[:8]}...)")

    device = BroadlinkDevice(
        host=ip, mac=mac_bytes, device_type=AC_DEVTYPE,
        device_id=0, key=aes_key, timeout=5.0,
    )

    # Auth
    try:
        device.auth()
        print(f"  Auth OK: device_id=0x{device.device_id:08X}")
    except RuntimeError as e:
        print(f"  Auth FAILED: {e}")
        return None

    # Swap to cloud key
    device.update_key(aes_key)

    # Status query
    params = {"did": did_hex, "sub_device_id": 0, "command_type": 0x02}
    payload = build_control_payload(params)
    print(f"  Sending status query ({len(payload)}B)...")

    try:
        result = device.send_command(payload)
        status_data = parse_status_payload(result.get("payload", b""))
        return status_data
    except RuntimeError as e:
        print(f"  Command FAILED: {e}")
        if "-6" in str(e):
            print(f"    errno -6 = Structure is abnormal:")
            print(f"    → wrong checksum, padding, or param IDs")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Kelvinator LAN device test")
    p.add_argument("--dry-run", action="store_true", help="Skip network, just verify imports")
    p.add_argument("--ips", nargs="+", default=["192.168.1.101", "192.168.1.102", "192.168.1.103"],
                   help="Direct-probe fallback IPs")
    p.add_argument("--skip-cloud", action="store_true",
                   help="Skip cloud login — use hardcoded device credentials from HAR capture")
    args = p.parse_args()

    print("=" * 60)
    print("Kelvinator LAN Device Test")
    print("=" * 60)

    if args.dry_run:
        print("\nDry run — checking imports...")
        print(f"  broadlink_api.device: {bl_dev.BroadlinkDevice}")
        print(f"  kelvinator_dna.protocol: {kd_proto.build_control_payload}")
        print(f"  kelvinator_dna.commands: {kd_cmds.ACMode}")
        print("All imports OK. Ready for live test.")
        return

    # Credentials
    if args.skip_cloud:
        # HAR-captured credentials — no cloud login needed
        devices = [
            {"did":"00000000000000000000a1b2c3d4e5f6","mac":"a1:b2:c3:d4:e5:f6",
             "name":"AC 1","aes_key":"00112233445566778899aabbccddeeff",
             "password":100000001,"devtype":20379,"pid":"9b4f0000"},
            {"did":"00000000000000000000a1b2c3d4e6f7","mac":"a1:b2:c3:d4:e6:f7",
             "name":"AC 2","aes_key":"11223344556677889900aabbccddeeff",
             "password":100000002,"devtype":20379,"pid":"9b4f0000"},
            {"did":"00000000000000000000a1b2c3d4e7f8","mac":"a1:b2:c3:d4:e7:f8",
             "name":"AC 3","aes_key":"223344556677889900aabbccddeeff",
             "password":100000003,"devtype":20379,"pid":"9b4f0000"},
        ]
        print("\nUsing HAR-captured device credentials (skipping cloud)")
        for d in devices:
            print(f"  {d['name']}: mac={d['mac']} did={d['did'][:8]}... key={d['aes_key'][:8]}...")
        ok = 2  # stages 1+2 skipped
        total = 2
    else:
        username = os.environ.get("KELVINATOR_USER", "")
        password = os.environ.get("KELVINATOR_PASS", "")
        if not username:
            username = input("Email/phone: ").strip()
        if not password:
            password = getpass("Password: ")
        if not username or not password:
            print("Empty credentials.")
            return

        ok = 0; total = 0

        # 1. Cloud login
        print("\n[1/4] Cloud login...")
        try:
            userid, loginsession = cloud_login(username, password)
            print(f"  OK: userid={userid[:8]}...")
            ok += 1
        except Exception as e:
            print(f"  FAIL: {e}"); traceback.print_exc()
        total += 1
        if not ok:
            print("\nCannot continue without cloud login."); return

        # 2. Device credentials
        print("\n[2/4] Fetching device credentials...")
        try:
            devices = cloud_get_devices(userid, loginsession)
            print(f"  OK: {len(devices)} device(s)")
            for d in devices:
                print(f"    {d['name']:20s} mac={d['mac']} did={d['did'][:8]}... key={d['aes_key'][:8]}...")
            ok += 1
        except Exception as e:
            print(f"  FAIL: {e}"); traceback.print_exc(); devices = []
        total += 1
        if not devices:
            print("\nNo devices to test."); return

    # 3. LAN discovery
    print("\n[3/4] LAN discovery...")
    mac_to_ip = {}
    try:
        lan = lan_discover(timeout=3.0)
        for ld in lan:
            mac_to_ip[ld["mac"].lower()] = ld["ip"]
        if mac_to_ip:
            ok += 1
            print(f"  {len(mac_to_ip)} device(s) found via broadcast")
        else:
            print("  Broadcast found nothing — trying direct probes...")
    except Exception as e:
        print(f"  Broadcast FAILED: {e}")
        traceback.print_exc()
    total += 1

    # Direct probes as fallback
    if not mac_to_ip:
        print(f"  Probing {args.ips}...")
        for ip in args.ips:
            mac = direct_probe(ip)
            if mac:
                mac_to_ip[mac.lower()] = ip
                print(f"  {ip} → mac={mac}")
        if mac_to_ip:
            ok += 1
            print(f"  {len(mac_to_ip)} device(s) found via direct probe")
        else:
            print("  FAIL: No devices found via broadcast or direct probe.")
            print("  Check: are devices on the same subnet? UDP port 80 reachable?")
            print("  Try: ping 192.168.1.101")

    # 4. UDP status for each device
    print("\n[4/4] Querying device status via UDP...")
    for cd in devices:
        total += 1
        ip = mac_to_ip.get(cd["mac"].lower())
        if not ip:
            print(f"\n  {cd['name']}: SKIP — not on LAN (mac={cd['mac']})")
            continue

        print(f"\n  {cd['name']}:")
        status = udp_status(ip, cd["mac"], cd["did"], cd["aes_key"], cd["password"])

        if status:
            ok += 1
            mode_names = {0: "COOL", 1: "HEAT", 2: "DRY", 3: "FAN", 4: "AUTO"}
            fan_names = {0: "AUTO", 1: "LOW", 2: "MED", 3: "HIGH", 4: "TURBO"}
            print(f"    Power: {'ON' if status.get('power') else 'OFF'}")
            print(f"    Mode:  {mode_names.get(status.get('mode'), '?')}")
            print(f"    Temp:  {status.get('temp')}°C")
            print(f"    Fan:   {fan_names.get(status.get('fan'), '?')}")
            print(f"    Room:  {status.get('room_temp')}°C")
            if status.get('error_code'):
                print(f"    Error: {status.get('error_code')}")
            print(f"    Raw:   {json.dumps({k: v for k, v in status.items() if not k.startswith('param_')}, default=str)}")
        else:
            print(f"    STATUS: FAILED")
            print(f"    Next steps:")
            print(f"    - Check device is on and connected to Wi-Fi")
            print(f"    - Verify AES key from cloud matches device")
            print(f"    - Capture UDP traffic: tcpdump -i any port 80 -w kelvinator.pcap")

    print(f"\n{'=' * 60}")
    print(f"Stages: {ok}/{total} passed")
    if ok == total:
        print("ALL STAGES PASSED — local UDP control works!")
    else:
        print("Some stages failed — see diagnostics above.")


if __name__ == "__main__":
    main()
