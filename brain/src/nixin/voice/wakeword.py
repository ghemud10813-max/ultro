"""Always-on wake word with openWakeWord (offline, CPU-friendly).

Pre-trained models include "hey_jarvis", "alexa", "hey_mycroft". A custom "hey nixin"
model can be trained for free with openWakeWord's Colab notebook; point
``voice.wake_word_model`` at the resulting .onnx/.tflite file.

Safety: commands started by the wake word can never send messages or place calls
without an explicit confirmation (see Actions._needs_confirm).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

CHUNK = 1280  # 80 ms at 16 kHz, what openWakeWord expects


class WakeWordListener:
    def __init__(self, model: str, threshold: float, device, on_trigger: Callable[[], None],
                 stop: threading.Event, pause: threading.Event) -> None:
        self.model_name = model
        self.threshold = threshold
        self.device = device
        self.on_trigger = on_trigger
        self.stop = stop
        self.pause = pause

    def run(self) -> None:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model

        if self.model_name.endswith((".onnx", ".tflite")):
            model = Model(wakeword_models=[self.model_name])
        else:
            try:
                import openwakeword

                openwakeword.utils.download_models([self.model_name])
            except Exception:
                pass
            model = Model(wakeword_models=[self.model_name])
        cooldown_until = 0.0
        while not self.stop.is_set():
            if self.pause.is_set():
                time.sleep(0.1)
                continue
            with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=CHUNK, device=self.device) as stream:
                while not self.stop.is_set() and not self.pause.is_set():
                    data, _ = stream.read(CHUNK)
                    scores = model.predict(np.asarray(data).reshape(-1))
                    if time.time() > cooldown_until and max(scores.values(), default=0) >= self.threshold:
                        cooldown_until = time.time() + 2.5
                        model.reset()
                        self.pause.set()  # release the mic for the recorder
                        self.on_trigger()
                        break
