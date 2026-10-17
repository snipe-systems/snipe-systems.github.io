"""Microphone capture with push-to-talk and silence-based auto-stop.

Uses `sounddevice` (cross-platform). Falls back cleanly if it isn't installed,
so the core pipeline and tests run without audio hardware.
"""

from __future__ import annotations

import time

import numpy as np

try:
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sd = None


class MicrophoneUnavailable(RuntimeError):
    pass


class Microphone:
    def __init__(self, sample_rate: int = 16000, device=None):
        self.sample_rate = sample_rate
        self.device = device

    def available(self) -> bool:
        return sd is not None

    def list_devices(self) -> list[dict]:
        if sd is None:
            return []
        return [dict(d) for d in sd.query_devices()]

    def record(self, max_seconds: float = 15.0, *, vad=None,
               silence_stop: float | None = None,
               stop_flag=None) -> np.ndarray | None:
        """Record until `max_seconds`, or until trailing silence exceeds
        `silence_stop` seconds (when a VAD is provided), or until `stop_flag()`
        returns True. Returns a float32 mono array at `sample_rate`."""
        if sd is None:
            raise MicrophoneUnavailable("sounddevice is not installed")
        if vad is None:
            vad = _NullVAD()

        chunks: list[np.ndarray] = []
        started = time.time()
        last_speech = time.time()

        def callback(indata, frames, t, status):  # noqa: D401
            chunks.append(indata[:, 0].copy())

        with sd.InputStream(samplerate=self.sample_rate, channels=1,
                            device=self.device, dtype="float32",
                            callback=callback, blocksize=1600):
            while True:
                time.sleep(0.03)
                if stop_flag is not None and stop_flag():
                    break
                if time.time() - started > max_seconds:
                    break
                if silence_stop is not None and len(chunks) >= 4:
                    recent = np.concatenate(chunks[-4:])
                    if vad.is_speech(recent):
                        last_speech = time.time()
                    elif time.time() - last_speech > silence_stop:
                        break

        if not chunks:
            return None
        audio = np.concatenate(chunks)
        if audio.size == 0:
            return None
        return audio.astype(np.float32)

    def record_fixed(self, seconds: float = 3.0) -> np.ndarray | None:
        return self.record(max_seconds=seconds, silence_stop=None)


class _NullVAD:
    def is_speech(self, _chunk) -> bool:
        return True
