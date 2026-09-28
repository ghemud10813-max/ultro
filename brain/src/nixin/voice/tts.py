"""Text-to-speech on the PC: edge-tts (free neural voices, online) -> pyttsx3 (offline) -> Piper (offline)."""

from __future__ import annotations

import asyncio
import shutil
import threading

from nixin.config import NixinConfig


class TtsEngine:
    name = "base"

    @property
    def available(self) -> bool:
        return False

    async def speak(self, text: str) -> None:
        raise NotImplementedError


class EdgeTts(TtsEngine):
    name = "edge"

    def __init__(self, voice: str) -> None:
        self.voice = voice

    @property
    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            import miniaudio  # noqa: F401
            import sounddevice  # noqa: F401

            return True
        except ImportError:
            return False

    async def speak(self, text: str) -> None:
        import edge_tts
        import miniaudio
        import numpy as np

        from nixin.voice.audio import play_pcm

        mp3 = bytearray()
        async for chunk in edge_tts.Communicate(text, self.voice).stream():
            if chunk["type"] == "audio":
                mp3 += chunk["data"]
        if not mp3:
            raise RuntimeError("edge-tts returned no audio")
        dec = miniaudio.decode(bytes(mp3), output_format=miniaudio.SampleFormat.SIGNED16)
        samples = np.frombuffer(dec.samples, dtype=np.int16)
        if dec.nchannels > 1:
            samples = samples.reshape(-1, dec.nchannels)
        await asyncio.to_thread(play_pcm, samples, dec.sample_rate)


class Pyttsx3Tts(TtsEngine):
    name = "pyttsx3"

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        try:
            import pyttsx3  # noqa: F401

            return True
        except ImportError:
            return False

    def _say(self, text: str) -> None:
        import pyttsx3

        with self._lock:
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
            engine.stop()

    async def speak(self, text: str) -> None:
        await asyncio.to_thread(self._say, text)


class PiperTts(TtsEngine):
    name = "piper"

    def __init__(self, model: str) -> None:
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.model) and shutil.which("piper") is not None

    async def speak(self, text: str) -> None:
        import json

        import numpy as np

        from nixin.voice.audio import play_pcm

        rate = 22050
        try:
            with open(self.model + ".json", encoding="utf-8") as f:
                rate = json.load(f)["audio"]["sample_rate"]
        except Exception:
            pass
        proc = await asyncio.create_subprocess_exec("piper", "--model", self.model, "--output_raw",
                                                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate(text.encode("utf-8"))
        await asyncio.to_thread(play_pcm, np.frombuffer(out, dtype=np.int16), rate)


class Speaker:
    """Queues replies so they never overlap; ``stop()`` interrupts playback."""

    def __init__(self, cfg: NixinConfig) -> None:
        all_engines = {"edge": EdgeTts(cfg.voice.edge_voice), "pyttsx3": Pyttsx3Tts(), "piper": PiperTts(cfg.voice.piper_model)}
        self.engines = [all_engines[n] for n in cfg.voice.tts if n in all_engines]
        self._lock = asyncio.Lock()
        self.muted = False

    @property
    def available(self) -> bool:
        return any(e.available for e in self.engines)

    async def say(self, text: str) -> None:
        if self.muted or not text.strip():
            return
        async with self._lock:
            for e in self.engines:
                if not e.available:
                    continue
                try:
                    await e.speak(text)
                    return
                except Exception:  # noqa: BLE001 — try next engine
                    continue

    async def wait_idle(self, settle: float = 0.15) -> None:
        """Wait until queued speech has finished (used before listening for a follow-up)."""
        await asyncio.sleep(settle)
        async with self._lock:
            pass

    def stop(self) -> None:
        from nixin.voice.audio import stop_playback

        stop_playback()
