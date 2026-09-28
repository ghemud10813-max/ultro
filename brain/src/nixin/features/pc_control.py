"""Control the PC itself: lock, sleep, shutdown, volume, media keys, open apps/sites,
screenshot, clipboard, typing and status. Lets you drive your computer from the phone
("PC lock karo", "laptop ka volume kam karo", "PC ka screenshot bhejo").

Windows is the primary target; Linux/macOS use the usual command-line tools. Optional
extras (pycaw, psutil, pyperclip) are used when installed, never required.
"""

from __future__ import annotations

import asyncio
import io
import os
import platform
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

Runner = Callable[[list[str]], Awaitable[tuple[int, str]]]

WEBSITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com", "whatsapp web": "https://web.whatsapp.com", "instagram": "https://www.instagram.com",
    "github": "https://github.com", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "maps": "https://maps.google.com",
    "netflix": "https://www.netflix.com", "spotify": "https://open.spotify.com", "twitter": "https://x.com", "x": "https://x.com",
    "linkedin": "https://www.linkedin.com", "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com",
    "drive": "https://drive.google.com", "calendar": "https://calendar.google.com", "news": "https://news.google.com",
}
WIN_APPS = {
    "notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint", "explorer": "explorer",
    "file explorer": "explorer", "files": "explorer", "task manager": "taskmgr", "cmd": "cmd", "terminal": "wt",
    "powershell": "powershell", "settings": "ms-settings:", "control panel": "control", "chrome": "chrome",
    "edge": "msedge", "vs code": "code", "vscode": "code", "code": "code", "word": "winword", "excel": "excel",
    "powerpoint": "powerpnt", "spotify": "spotify", "camera": "microsoft.windows.camera:", "snipping tool": "snippingtool",
}


async def _default_runner(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), 20)
    return proc.returncode or 0, out.decode(errors="replace").strip()


class PcError(Exception):
    pass


@dataclass
class PcStatus:
    cpu: float | None
    ram: float | None
    battery: int | None
    charging: bool | None
    host: str
    os: str


class PcControl:
    def __init__(self, runner: Runner | None = None, system: str | None = None) -> None:
        self.run = runner or _default_runner
        self.system = system or platform.system()  # Windows | Linux | Darwin
        self.last_shutdown: str | None = None

    # ------------------------------------------------------------------ power
    async def lock(self) -> str:
        if self.system == "Windows":
            try:
                import ctypes

                ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
                return "locked"
            except Exception:
                await self.run(["rundll32.exe", "user32.dll,LockWorkStation"])
                return "locked"
        if self.system == "Darwin":
            await self.run(["pmset", "displaysleepnow"])
            return "locked"
        for cmd in (["loginctl", "lock-session"], ["xdg-screensaver", "lock"], ["gnome-screensaver-command", "-l"]):
            if shutil.which(cmd[0]):
                await self.run(cmd)
                return "locked"
        raise PcError("No screen-lock command found")

    async def sleep(self) -> str:
        if self.system == "Windows":
            await self.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif self.system == "Darwin":
            await self.run(["pmset", "sleepnow"])
        else:
            await self.run(["systemctl", "suspend"])
        return "sleeping"

    async def shutdown(self, restart: bool = False, delay_seconds: int = 60) -> str:
        """Scheduled with a delay so it can still be cancelled ("shutdown cancel karo")."""
        if self.system == "Windows":
            await self.run(["shutdown", "/r" if restart else "/s", "/t", str(delay_seconds)])
        elif self.system == "Darwin":
            await self.run(["sudo", "shutdown", "-r" if restart else "-h", f"+{max(1, delay_seconds // 60)}"])
        else:
            await self.run(["shutdown", "-r" if restart else "-h", f"+{max(1, delay_seconds // 60)}"])
        self.last_shutdown = "restart" if restart else "shutdown"
        return self.last_shutdown

    async def cancel_shutdown(self) -> str:
        if self.system == "Windows":
            await self.run(["shutdown", "/a"])
        else:
            await self.run(["shutdown", "-c"])
        self.last_shutdown = None
        return "cancelled"

    # ------------------------------------------------------------------ volume & media
    def _pycaw(self):
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL  # type: ignore
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

            dev = AudioUtilities.GetSpeakers()
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(iface, POINTER(IAudioEndpointVolume))
        except Exception:
            return None

    def _press(self, key_name: str, times: int = 1) -> None:
        from pynput.keyboard import Controller, Key  # voice extra

        kb = Controller()
        key = getattr(Key, key_name)
        for _ in range(times):
            kb.press(key)
            kb.release(key)

    async def volume(self, action: str, percent: int | None = None, steps: int = 3) -> str:
        if self.system == "Windows":
            vol = self._pycaw()
            if vol is not None:
                cur = vol.GetMasterVolumeLevelScalar()
                if action == "set" and percent is not None:
                    vol.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100, None)
                elif action in ("up", "down"):
                    delta = 0.06 * steps * (1 if action == "up" else -1)
                    vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, cur + delta)), None)
                elif action == "max":
                    vol.SetMasterVolumeLevelScalar(1.0, None)
                elif action in ("mute", "unmute"):
                    vol.SetMute(1 if action == "mute" else 0, None)
                return f"{round(vol.GetMasterVolumeLevelScalar() * 100)}%"
            # fallback: media keys (each press is ~2%)
            key = {"up": "media_volume_up", "down": "media_volume_down", "mute": "media_volume_mute",
                   "unmute": "media_volume_mute", "max": "media_volume_up"}.get(action)
            if key is None and action == "set":
                raise PcError("Setting an exact PC volume needs `pip install pycaw`")
            await asyncio.to_thread(self._press, key, 50 if action == "max" else (1 if "mute" in action else steps * 3))
            return action
        if self.system == "Darwin":
            script = {"up": "set volume output volume ((output volume of (get volume settings)) + 10)",
                      "down": "set volume output volume ((output volume of (get volume settings)) - 10)",
                      "mute": "set volume with output muted", "unmute": "set volume without output muted",
                      "max": "set volume output volume 100",
                      "set": f"set volume output volume {percent or 50}"}[action]
            await self.run(["osascript", "-e", script])
            return action
        arg = {"up": "5%+", "down": "5%-", "mute": "mute", "unmute": "unmute", "max": "100%",
               "set": f"{percent or 50}%"}[action]
        await self.run(["amixer", "-q", "sset", "Master", arg])
        return action

    async def media(self, action: str) -> str:
        key = {"play": "media_play_pause", "pause": "media_play_pause", "toggle": "media_play_pause",
               "next": "media_next", "previous": "media_previous"}.get(action)
        if key is None:
            raise PcError(f"Unknown media action {action}")
        if self.system == "Linux" and shutil.which("playerctl"):
            await self.run(["playerctl", {"media_play_pause": "play-pause", "media_next": "next",
                                          "media_previous": "previous"}[key]])
        else:
            await asyncio.to_thread(self._press, key)
        return action

    # ------------------------------------------------------------------ open things
    async def open(self, target: str) -> str:
        t = target.strip()
        low = t.lower().removesuffix(" app").strip()
        if low.startswith(("http://", "https://")) or ("." in low and " " not in low and not low.endswith(".exe")):
            url = t if low.startswith("http") else "https://" + t
            await asyncio.to_thread(webbrowser.open, url)
            return url
        if low in WEBSITES and low not in WIN_APPS:
            await asyncio.to_thread(webbrowser.open, WEBSITES[low])
            return WEBSITES[low]
        if self.system == "Windows":
            exe = WIN_APPS.get(low, low)
            try:
                await asyncio.to_thread(os.startfile, exe)  # type: ignore[attr-defined]
                return exe
            except OSError:
                if low in WEBSITES:
                    await asyncio.to_thread(webbrowser.open, WEBSITES[low])
                    return WEBSITES[low]
                raise PcError(f"Couldn't open '{target}' on the PC") from None
        if self.system == "Darwin":
            code, _ = await self.run(["open", "-a", t])
            if code == 0:
                return t
        elif shutil.which(low):
            await asyncio.to_thread(subprocess.Popen, [low], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            return low
        if low in WEBSITES:
            await asyncio.to_thread(webbrowser.open, WEBSITES[low])
            return WEBSITES[low]
        raise PcError(f"Couldn't open '{target}' on the PC")

    async def search(self, query: str) -> str:
        from urllib.parse import quote_plus

        url = "https://www.google.com/search?q=" + quote_plus(query)
        await asyncio.to_thread(webbrowser.open, url)
        return url

    # ------------------------------------------------------------------ screenshot / clipboard / typing
    async def screenshot(self, max_width: int = 1920, quality: int = 80) -> bytes:
        def grab() -> bytes:
            from PIL import ImageGrab

            img = ImageGrab.grab(all_screens=True).convert("RGB")
            if img.width > max_width:
                img = img.resize((max_width, int(img.height * max_width / img.width)))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()

        try:
            return await asyncio.to_thread(grab)
        except Exception as e:  # noqa: BLE001
            raise PcError(f"Screenshot failed: {e}") from e

    async def clipboard_get(self) -> str:
        try:
            import pyperclip  # type: ignore

            return await asyncio.to_thread(pyperclip.paste)
        except ImportError:
            pass
        if self.system == "Windows":
            _, out = await self.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"])
            return out
        if self.system == "Darwin":
            _, out = await self.run(["pbpaste"])
            return out
        for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]):
            if shutil.which(cmd[0]):
                _, out = await self.run(cmd)
                return out
        raise PcError("No clipboard tool found (pip install pyperclip)")

    async def clipboard_set(self, text: str) -> None:
        try:
            import pyperclip  # type: ignore

            await asyncio.to_thread(pyperclip.copy, text)
            return
        except ImportError:
            pass

        def via_stdin(cmd: list[str]) -> None:
            subprocess.run(cmd, input=text.encode("utf-8" if cmd[0] != "clip" else "utf-16-le"), check=False)

        if self.system == "Windows":
            await asyncio.to_thread(via_stdin, ["clip"])
        elif self.system == "Darwin":
            await asyncio.to_thread(via_stdin, ["pbcopy"])
        else:
            for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
                if shutil.which(cmd[0]):
                    await asyncio.to_thread(via_stdin, cmd)
                    return
            raise PcError("No clipboard tool found (pip install pyperclip)")

    async def type_text(self, text: str) -> None:
        def typ() -> None:
            from pynput.keyboard import Controller

            Controller().type(text)

        await asyncio.to_thread(typ)

    # ------------------------------------------------------------------ status / notify
    async def status(self) -> PcStatus:
        cpu = ram = None
        battery = None
        charging = None
        try:
            import psutil  # type: ignore

            cpu = psutil.cpu_percent(interval=0.3)
            ram = psutil.virtual_memory().percent
            b = psutil.sensors_battery()
            if b is not None:
                battery, charging = int(b.percent), bool(b.power_plugged)
        except ImportError:
            pass
        return PcStatus(cpu, ram, battery, charging, platform.node(), f"{platform.system()} {platform.release()}")

    async def notify(self, title: str, text: str) -> None:
        """Desktop notification (Windows toast via winotify if installed; notify-send on Linux)."""
        try:
            if self.system == "Windows":
                from winotify import Notification  # type: ignore

                Notification(app_id="Nixin", title=title, msg=text[:250]).show()
            elif self.system == "Darwin":
                def q(v: str) -> str:
                    return v.replace("\\", " ").replace('"', "'")

                await self.run(["osascript", "-e", f'display notification "{q(text[:200])}" with title "{q(title)}"'])
            elif shutil.which("notify-send"):
                await self.run(["notify-send", title, text[:250]])
        except Exception:
            pass

    @staticmethod
    def platform_summary() -> str:
        return f"{platform.system()} {platform.release()} · Python {sys.version.split()[0]}"
