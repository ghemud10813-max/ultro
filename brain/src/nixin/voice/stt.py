"""Speech-to-text: Groq Whisper (free, fast, cloud) with offline faster-whisper fallback."""

from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass

import httpx

from nixin.config import NixinConfig, get_secret_pool


@dataclass
class Transcript:
    text: str
    confidence: float | None
    engine: str
    language: str | None = None


class SttError(Exception):
    pass


class GroqWhisper:
    name = "groq"

    def __init__(self, cfg: NixinConfig, http: httpx.AsyncClient) -> None:
        self.cfg = cfg
        self.http = http
        self.keys = get_secret_pool("GROQ_API_KEY")
        self._key_idx = 0
        self.base = cfg.providers["groq"].base_url if "groq" in cfg.providers else "https://api.groq.com/openai/v1"

    @property
    def available(self) -> bool:
        return bool(self.keys) and self.cfg.privacy.cloud_stt

    async def transcribe(self, wav: bytes) -> Transcript:
        if not self.available:
            raise SttError("Groq STT unavailable (no key or cloud STT disabled)")
        v = self.cfg.voice
        data = {"model": v.groq_stt_model, "response_format": "verbose_json", "temperature": "0"}
        if v.stt_language:
            data["language"] = v.stt_language
        if v.stt_prompt:
            data["prompt"] = v.stt_prompt
        last: Exception | None = None
        for _ in range(len(self.keys)):
            key = self.keys[self._key_idx % len(self.keys)]
            try:
                r = await self.http.post(self.base.rstrip("/") + "/audio/transcriptions", data=data,
                                         files={"file": ("speech.wav", wav, "audio/wav")},
                                         headers={"Authorization": f"Bearer {key}"}, timeout=30)
            except httpx.HTTPError as e:
                last = e
                break
            if r.status_code == 429 or r.status_code in (401, 403):
                self._key_idx += 1
                last = SttError(f"Groq STT HTTP {r.status_code}")
                continue
            if r.status_code >= 400:
                raise SttError(f"Groq STT HTTP {r.status_code}: {r.text[:200]}")
            j = r.json()
            segs = j.get("segments") or []
            conf = None
            if segs:
                lp = [s.get("avg_logprob") for s in segs if s.get("avg_logprob") is not None]
                ns = [s.get("no_speech_prob") for s in segs if s.get("no_speech_prob") is not None]
                if lp:
                    conf = max(0.0, min(1.0, math.exp(sum(lp) / len(lp))))
                    if ns and sum(ns) / len(ns) > 0.6:
                        conf = min(conf, 0.2)
            return Transcript((j.get("text") or "").strip(), conf, "groq", j.get("language"))
        raise SttError(f"Groq STT failed: {last}")


class LocalWhisper:
    name = "local"

    def __init__(self, cfg: NixinConfig) -> None:
        self.cfg = cfg
        self._model = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            try:
                self._model = WhisperModel(self.cfg.voice.local_stt_model, device="auto", compute_type="int8")
            except Exception:
                self._model = WhisperModel(self.cfg.voice.local_stt_model, device="cpu", compute_type="int8")
        return self._model

    def _run(self, wav: bytes) -> Transcript:
        model = self._load()
        v = self.cfg.voice
        segments, info = model.transcribe(io.BytesIO(wav), language=v.stt_language or None, vad_filter=True,
                                          beam_size=1, initial_prompt=v.stt_prompt or None)
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        conf = None
        if segs:
            conf = max(0.0, min(1.0, math.exp(sum(s.avg_logprob for s in segs) / len(segs))))
        return Transcript(text, conf, "local", getattr(info, "language", None))

    async def transcribe(self, wav: bytes) -> Transcript:
        if not self.available:
            raise SttError("faster-whisper not installed (pip install nixin[local-stt])")
        async with self._lock:
            return await asyncio.to_thread(self._run, wav)


class SttChain:
    def __init__(self, cfg: NixinConfig, http: httpx.AsyncClient) -> None:
        engines = {"groq": GroqWhisper(cfg, http), "local": LocalWhisper(cfg)}
        self.engines = [engines[n] for n in cfg.voice.stt if n in engines]

    @property
    def available(self) -> bool:
        return any(e.available for e in self.engines)

    async def transcribe(self, wav: bytes) -> Transcript:
        errors = []
        for e in self.engines:
            if not e.available:
                continue
            try:
                return await e.transcribe(wav)
            except Exception as ex:  # noqa: BLE001
                errors.append(f"{e.name}: {ex}")
        raise SttError("; ".join(errors) or "No speech-to-text engine available")
