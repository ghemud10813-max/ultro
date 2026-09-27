"""Voice loop: global hotkeys (push-to-talk, kill switch), optional wake word, STT -> Brain, TTS.

  Ctrl+Alt+N  -> beep, listen until you stop talking, transcribe, run the command
  Ctrl+Alt+K  -> cancel whatever Nixin is doing (PC kill switch)
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import httpx

from nixin.voice.audio import Recorder, VadConfig, end_cue, start_cue
from nixin.voice.stt import SttChain
from nixin.voice.tts import Speaker

if TYPE_CHECKING:
    from nixin.app import NixinApp

LOW_CONFIDENCE = 0.35


class VoiceLoop:
    def __init__(self, app: NixinApp) -> None:
        self.app = app
        self.cfg = app.cfg
        self.bus = app.bus
        self.http = httpx.AsyncClient(timeout=40)
        self.stt = SttChain(self.cfg, self.http)
        self.speaker = Speaker(self.cfg)
        self.recorder = Recorder(self.cfg.voice.input_device)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._listening = False
        self._hotkeys = None
        self._wake: threading.Thread | None = None
        self._wake_stop = threading.Event()
        self._wake_pause = threading.Event()

    def _vad(self, max_seconds: float | None = None) -> VadConfig:
        v = self.cfg.voice
        return VadConfig(max_seconds=max_seconds or v.max_record_seconds, silence_seconds=v.silence_seconds)

    async def start(self) -> None:
        import sounddevice  # noqa: F401 — fail fast when the voice extra is missing

        self.loop = asyncio.get_running_loop()
        if self.speaker.available:
            self.app.brain.speaker = self.speaker
            self.app.gate.speak = self.speaker.say
        self.app.gate.voice_listen = self.listen_once
        self._start_hotkeys()
        if self.cfg.voice.wake_word:
            self._start_wake_word()
        engines = [e.name for e in self.stt.engines if e.available]
        self.bus.emit("log", level="info",
                      msg=f"Voice ready — push-to-talk {self.cfg.voice.push_to_talk}, kill {self.cfg.voice.kill_switch}; "
                          f"STT: {', '.join(engines) or 'none (add GROQ_API_KEY or install nixin[local-stt])'}; "
                          f"TTS: {', '.join(e.name for e in self.speaker.engines if e.available) or 'none'}")

    def _start_hotkeys(self) -> None:
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            self.bus.emit("log", level="warning", msg=f"Hotkeys unavailable: {e}")
            return

        def ptt() -> None:
            if self.loop:
                asyncio.run_coroutine_threadsafe(self.push_to_talk("voice"), self.loop)

        def kill() -> None:
            if self.loop:
                self.loop.call_soon_threadsafe(self._kill)

        self._hotkeys = keyboard.GlobalHotKeys({self.cfg.voice.push_to_talk: ptt, self.cfg.voice.kill_switch: kill})
        self._hotkeys.start()

    def _kill(self) -> None:
        self.recorder.abort.set()
        msg = self.app.brain.cancel_current()
        self.bus.emit("log", level="warning", msg=f"PC kill switch: {msg}")

    async def push_to_talk(self, source: str = "voice") -> None:
        if self._listening:
            self.recorder.abort.set()  # second press = stop listening early
            return
        self._listening = True
        self._wake_pause.set()
        try:
            self.speaker.stop()
            self.bus.emit("listening", on=True, source=source)
            await asyncio.to_thread(start_cue)
            wav = await asyncio.to_thread(self.recorder.record, self._vad())
            self.bus.emit("listening", on=False)
            if not wav:
                return
            await asyncio.to_thread(end_cue)
            try:
                tr = await self.stt.transcribe(wav)
            except Exception as e:  # noqa: BLE001
                self.bus.emit("log", level="error", msg=f"Speech-to-text failed: {e}")
                await self.speaker.say("Sun nahi paya, dobara bolo.")
                return
            self.bus.emit("heard", text=tr.text, confidence=tr.confidence, engine=tr.engine)
            if not tr.text:
                return
            if tr.confidence is not None and tr.confidence < LOW_CONFIDENCE:
                await self.speaker.say("Theek se samajh nahi aaya, dobara bolo.")
                return
            await self.app.brain.handle(tr.text, source=source)
        finally:
            self._listening = False
            self._wake_pause.clear()

    async def listen_once(self, max_seconds: float) -> str | None:
        """Short capture used for yes/no confirmations."""
        if self._listening:
            return None
        self._listening = True
        self._wake_pause.set()
        try:
            await asyncio.to_thread(start_cue)
            wav = await asyncio.to_thread(self.recorder.record, self._vad(max_seconds))
            if not wav:
                return None
            tr = await self.stt.transcribe(wav)
            self.bus.emit("heard", text=tr.text, confidence=tr.confidence, engine=tr.engine)
            return tr.text
        except Exception:  # noqa: BLE001
            return None
        finally:
            self._listening = False
            self._wake_pause.clear()

    # ------------------------------------------------------------------ wake word
    def _start_wake_word(self) -> None:
        try:
            from nixin.voice.wakeword import WakeWordListener
        except Exception as e:  # noqa: BLE001
            self.bus.emit("log", level="warning", msg=f"Wake word unavailable: {e}")
            return

        def triggered() -> None:
            if self.loop and not self._listening:
                asyncio.run_coroutine_threadsafe(self.push_to_talk("wake_word"), self.loop)

        listener = WakeWordListener(self.cfg.voice.wake_word_model, self.cfg.voice.wake_word_threshold,
                                    self.cfg.voice.input_device, triggered, self._wake_stop, self._wake_pause)
        self._wake = threading.Thread(target=listener.run, name="nixin-wakeword", daemon=True)
        self._wake.start()
        self.bus.emit("log", level="info", msg=f"Wake word '{self.cfg.voice.wake_word_model}' listening")

    async def stop(self) -> None:
        self._wake_stop.set()
        self.recorder.abort.set()
        if self._hotkeys:
            self._hotkeys.stop()
        await self.http.aclose()
