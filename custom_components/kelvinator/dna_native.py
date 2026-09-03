"""
Async client for the bundled BroadLink DNA SDK native bridge.

Runs dna_sdk/dna_bridge.py as a subprocess (the Android-NDK SO needs
LD_LIBRARY_PATH / LD_PRELOAD env tricks, so it must be a child process).
One JSON request/response per line over stdin/stdout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

_SDK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dna_sdk")


class NativeDNAError(Exception):
    """Bridge call failed."""


class NativeDNAClient:
    """Manages the dna_bridge subprocess and JSON-RPC-ish calls."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._proc and self._proc.returncode is None:
                return
            env = dict(os.environ)
            env["LD_LIBRARY_PATH"] = _SDK_DIR
            env["LD_PRELOAD"] = os.path.join(_SDK_DIR, "shim_internal.so")
            self._proc = await asyncio.create_subprocess_exec(
                "python3", "-u", os.path.join(_SDK_DIR, "dna_bridge.py"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None

    async def _call(self, op: str, **kwargs: Any) -> dict[str, Any]:
        if not self._proc or self._proc.returncode is not None:
            await self.start()
        assert self._proc and self._proc.stdin and self._proc.stdout
        req = json.dumps({"op": op, **kwargs}, separators=(",", ":")) + "\n"
        async with self._lock:
            self._proc.stdin.write(req.encode())
            await self._proc.stdin.drain()
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30)
        if not line:
            raise NativeDNAError("bridge died — restarting on next call")
        out = json.loads(line.decode())
        if not out.get("ok"):
            raise NativeDNAError(out.get("error", "unknown bridge error"))
        resp = out.get("resp")
        try:
            return json.loads(resp) if resp else {}
        except ValueError:
            return {"raw": resp}

    # -- convenience wrappers ------------------------------------------------

    async def sdk_init(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self._call("init", config=config)

    async def sdk_auth(self, args: list[str]) -> dict[str, Any]:
        return await self._call("auth", args=args)

    async def ctrl(
        self,
        dev: dict[str, Any],
        sub: dict[str, Any],
        data: dict[str, Any],
        desc: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._call("ctrl", dev=dev, sub=sub, data=data, desc=desc)

    async def device_request(
        self, dev: dict[str, Any], act: str, params: list[str],
        vals: list[list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """dev_ctrl request/response for one device (cloud relay path)."""
        sub = {
            "did": dev["did"],
            "pid": dev.get("pid", ""),
            "name": dev.get("name", ""),
        }
        data = {"act": act, "params": params, "vals": vals}
        desc = {"name": "dev_ctrl", "command": "dev_ctrl", "cookie": "aabb"}
        return await self.ctrl(dev, sub, data, desc)

    async def build_packet(
        self, dev: dict[str, Any], act: str, params: list[str],
        vals: list[list[dict[str, Any]]],
    ) -> bytes:
        """dev_data build — returns the plaintext Lua/DNA packet (no send)."""
        import base64
        sub = {"did": dev["did"], "pid": dev.get("pid", ""), "name": dev.get("name", "")}
        data = {"act": act, "params": params, "vals": vals}
        desc = {"name": "dev_data", "command": "dev_data", "cookie": "aabb"}
        resp = await self.ctrl(dev, sub, data, desc)
        b64 = (resp.get("data") or {}).get("ctrldata")
        if not b64:
            raise NativeDNAError(f"no ctrldata in response: {resp}")
        return base64.b64decode(b64)