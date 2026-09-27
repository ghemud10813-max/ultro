"""Optional ADB "power mode": things Android forbids normal apps from doing.

Off by default. Only fixed command templates exist — there is no way (for the LLM or
anyone else) to run an arbitrary shell command through Nixin.

Enable: Developer options -> Wireless debugging -> pair with `adb pair`, then set
[adb] enabled = true and serial = "<ip>:<port>" in nixin.toml.
"""

from __future__ import annotations

import asyncio
import shutil

from nixin.config import AdbConfig
from nixin.core.events import EventBus

# setting -> (on command, off command)
TOGGLE_TEMPLATES: dict[str, tuple[list[str], list[str]]] = {
    "wifi": (["shell", "svc", "wifi", "enable"], ["shell", "svc", "wifi", "disable"]),
    "mobile_data": (["shell", "svc", "data", "enable"], ["shell", "svc", "data", "disable"]),
    "bluetooth": (["shell", "cmd", "bluetooth_manager", "enable"], ["shell", "cmd", "bluetooth_manager", "disable"]),
    "airplane": (["shell", "cmd", "connectivity", "airplane-mode", "enable"],
                 ["shell", "cmd", "connectivity", "airplane-mode", "disable"]),
    "location": (["shell", "cmd", "location", "set-location-enabled", "true"],
                 ["shell", "cmd", "location", "set-location-enabled", "false"]),
}


class AdbError(Exception):
    pass


class AdbPower:
    def __init__(self, cfg: AdbConfig, bus: EventBus) -> None:
        self.cfg = cfg
        self.bus = bus

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled and bool(self.cfg.serial) and shutil.which(self.cfg.adb_path) is not None

    def supports_toggle(self, setting: str) -> bool:
        return setting in TOGGLE_TEMPLATES

    async def _run(self, args: list[str], timeout: float = 15) -> str:
        if not self.enabled:
            raise AdbError("ADB power mode is disabled")
        cmd = [self.cfg.adb_path, "-s", self.cfg.serial, *args]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            raise AdbError("adb timed out") from None
        self.bus.emit("log", level="info", msg=f"ADB: {' '.join(args[:4])} -> {proc.returncode}")
        if proc.returncode != 0:
            raise AdbError((err or out).decode(errors="replace").strip()[:300])
        return out.decode(errors="replace")

    async def connect(self) -> str:
        if not (self.cfg.enabled and self.cfg.serial):
            raise AdbError("ADB power mode is disabled")
        proc = await asyncio.create_subprocess_exec(self.cfg.adb_path, "connect", self.cfg.serial,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
        return out.decode(errors="replace").strip()

    async def toggle(self, setting: str, on: bool) -> None:
        on_cmd, off_cmd = TOGGLE_TEMPLATES[setting]
        await self._run(on_cmd if on else off_cmd)

    async def screenrecord(self, seconds: int, remote: str = "/sdcard/Movies/nixin.mp4") -> str:
        seconds = max(1, min(180, int(seconds)))
        await self._run(["shell", "screenrecord", "--time-limit", str(seconds), remote], timeout=seconds + 15)
        return remote

    async def install_apk(self, path: str) -> str:
        if not path.lower().endswith(".apk"):
            raise AdbError("Only .apk files can be installed")
        return await self._run(["install", "-r", path], timeout=180)
