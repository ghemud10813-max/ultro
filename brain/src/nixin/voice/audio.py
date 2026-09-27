"""Microphone capture with a simple energy-based VAD, WAV encoding, playback and cues.

Needs the ``voice`` extra (numpy + sounddevice). Imports are lazy so the rest of Nixin
works on machines without audio hardware.
"""

from __future__ import annotations

import io
import threading
import time
import wave
from dataclasses import dataclass

SAMPLE_RATE = 16_000
FRAME_MS = 30


def _np():
    import numpy as np

    return np


def _sd():
    import sounddevice as sd

    return sd


@dataclass
class VadConfig:
    max_seconds: float = 12.0
    silence_seconds: float = 1.2
    start_timeout: float = 5.0  # give up if nothing is said
    min_speech_seconds: float = 0.3
    threshold_multiplier: float = 3.0
    min_threshold: float = 350.0  # int16 RMS


class EnergyVad:
    """Adaptive threshold: calibrates on the first ~300 ms of room noise."""

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.noise: list[float] = []
        self.threshold = cfg.min_threshold
        self.speech_frames = 0
        self.silence_frames = 0
        self.started = False
        self.frames = 0

    def push(self, rms: float) -> str:
        """Feed one frame's RMS. Returns 'wait' | 'speech' | 'end' | 'timeout'."""
        self.frames += 1
        fps = 1000 / FRAME_MS
        if len(self.noise) < 10 and not self.started:
            self.noise.append(rms)
            self.threshold = max(self.cfg.min_threshold, (sum(self.noise) / len(self.noise)) * self.cfg.threshold_multiplier)
        if rms >= self.threshold:
            self.speech_frames += 1
            self.silence_frames = 0
            if self.speech_frames >= 3:
                self.started = True
        else:
            self.silence_frames += 1
        if self.frames / fps >= self.cfg.max_seconds:
            return "end" if self.started else "timeout"
        if not self.started:
            return "timeout" if self.frames / fps >= self.cfg.start_timeout else "wait"
        if self.silence_frames / fps >= self.cfg.silence_seconds and self.speech_frames / fps >= self.cfg.min_speech_seconds:
            return "end"
        return "speech"


def to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Recorder:
    """Records one utterance at a time. Thread-safe; call from a worker thread."""

    def __init__(self, device: str | int | None = None) -> None:
        self.device = device
        self._lock = threading.Lock()
        self.abort = threading.Event()

    def record(self, vad: VadConfig) -> bytes | None:
        """Blocking. Returns WAV bytes, or None if nothing was said / aborted."""
        np, sd = _np(), _sd()
        with self._lock:
            self.abort.clear()
            v = EnergyVad(vad)
            chunks: list[bytes] = []
            block = int(SAMPLE_RATE * FRAME_MS / 1000)
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=block, channels=1, dtype="int16",
                                   device=self.device) as stream:
                while not self.abort.is_set():
                    data, _ = stream.read(block)
                    b = bytes(data)
                    chunks.append(b)
                    arr = np.frombuffer(b, dtype=np.int16).astype(np.float32)
                    state = v.push(float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0)
                    if state == "end":
                        break
                    if state == "timeout":
                        return None
            if self.abort.is_set() or not v.started:
                return None
            return to_wav(b"".join(chunks))


def play_pcm(samples, rate: int) -> None:
    """Blocking playback of a numpy float32/int16 array."""
    sd = _sd()
    sd.play(samples, rate)
    sd.wait()


def stop_playback() -> None:
    try:
        _sd().stop()
    except Exception:
        pass


def beep(freq: float = 880.0, ms: int = 90, volume: float = 0.25) -> None:
    try:
        np = _np()
        t = np.linspace(0, ms / 1000, int(22050 * ms / 1000), False)
        tone = (np.sin(2 * np.pi * freq * t) * volume).astype(np.float32)
        fade = np.minimum(1, np.minimum(np.arange(tone.size), np.arange(tone.size)[::-1]) / 200)
        play_pcm(tone * fade, 22050)
    except Exception:
        pass


def start_cue() -> None:
    beep(880, 70)
    time.sleep(0.02)


def end_cue() -> None:
    beep(620, 70)
