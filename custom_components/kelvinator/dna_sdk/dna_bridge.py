#!/usr/bin/env python3
"""
dna_bridge.py — subprocess bridge to the bundled BroadLink DNA SDK (libNetworkAPI.so).

The SO is an Android-NDK x86-64 build that loads on Linux with:
  - LD_LIBRARY_PATH pointing at this directory (bionic-named lib copies/symlinks)
  - LD_PRELOAD of shim_internal.so (bionic-only symbol shims: __sF, __errno,
    __assert2, __android_log_*)

It is driven over stdin/stdout, one JSON object per line:

  -> {"op": "init", "config": {...}}
  -> {"op": "auth", "args": [13 strings]}
  -> {"op": "ctrl", "dev": {...}, "sub": {...}, "data": {...}, "desc": {...}}
  <- {"ok": true, "resp": "<raw JSON string from SDK>"}

Kept deliberately dependency-free (stdlib only) so it can run beside HA.
"""

import json
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))

_lib = None


def _ensure_lib_links():
    """bionic-named DT_NEEDED entries (libc.so etc) need same-named files here.
    Symlink them to the host's glibc (find via common paths)."""
    import ctypes.util
    pairs = {
        "libc.so": "libc.so.6", "libm.so": "libm.so.6", "libdl.so": "libdl.so.2",
        "libstdc++.so": "libstdc++.so.6", "libz.so": "libz.so.1",
    }
    for bname, real in pairs.items():
        target = os.path.join(_DIR, bname)
        if os.path.exists(target):
            continue
        src = ctypes.util.find_library(real.rstrip(".0123456789")) or ""
        if not src or not os.path.exists(src):
            # common fallback locations
            for cand in ("/lib64/" + real, "/usr/lib64/" + real, "/lib/" + real,
                         "/usr/lib/" + real):
                if os.path.exists(cand):
                    src = cand
                    break
        if src and os.path.exists(src):
            try:
                os.symlink(src, target)
            except OSError:
                pass


def _load():
    global _lib
    if _lib is not None:
        return _lib
    import ctypes
    _ensure_lib_links()
    lib = ctypes.CDLL(os.path.join(_DIR, "kelvinator_native.so"))
    lib.dna_sdk_init.restype = ctypes.c_void_p
    lib.dna_sdk_auth.restype = ctypes.c_void_p
    lib.dna_sdk_ctrl.restype = ctypes.c_void_p
    _lib = lib
    return lib


def _read_cstr(ptr):
    if not ptr:
        return None
    import ctypes
    return ctypes.string_at(ptr, 65536).split(b"\0")[0].decode("utf-8", "replace")


def op_init(req):
    lib = _load()
    config = json.dumps(req["config"], separators=(",", ":")).encode()
    return {"ok": True, "resp": _read_cstr(lib.dna_sdk_init(config))}


def op_auth(req):
    lib = _load()
    args = [a.encode() if isinstance(a, str) else a for a in req["args"]]
    arr = (ctypes.c_char_p * len(args))(*args)
    return {"ok": True, "resp": _read_cstr(lib.dna_sdk_auth(arr))}


def op_ctrl(req):
    lib = _load()
    dev = json.dumps(req["dev"], separators=(",", ":")).encode()
    sub = json.dumps(req["sub"], separators=(",", ":")).encode()
    data = json.dumps(req["data"], separators=(",", ":")).encode()
    desc = json.dumps(req["desc"], separators=(",", ":")).encode()
    return {
        "ok": True,
        "resp": _read_cstr(lib.dna_sdk_ctrl(dev, sub, data, desc)),
    }


OPS = {"init": op_init, "auth": op_auth, "ctrl": op_ctrl}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            out = OPS[req["op"]](req)
        except Exception as exc:  # noqa: BLE001 — report everything to parent
            out = {"ok": False, "error": repr(exc)}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    os._exit(0)  # SO cleanup segfaults at interpreter exit; skip it


if __name__ == "__main__":
    main()