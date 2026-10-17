"""Voice-activity detection.

An energy-based VAD is provided as a zero-dependency baseline (RMS threshold),
plus an optional Silero VAD for better noise robustness when onnxruntime is
available.
"""

from __future__ import annotations

import numpy as np


class EnergyVAD:
    def __init__(self, threshold: float = 0.015):
        self.threshold = threshold

    def is_speech(self, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
        return rms > self.threshold


class SileroVAD:
    """Optional. Uses the silero-vad ONNX model if onnxruntime is installed."""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None
        try:
            import onnxruntime as ort  # type: ignore
            self._ort = ort
        except Exception:
            self._ort = None
        self._fallback = EnergyVAD()

    def _load(self) -> None:
        if self._model is not None or self._ort is None:
            return
        try:
            from silero_vad import load_silero_vad  # type: ignore
            self._model = load_silero_vad(onnx=True)
        except Exception:
            self._model = False

    def is_speech(self, audio: np.ndarray) -> bool:
        if self._ort is None:
            return self._fallback.is_speech(audio)
        self._load()
        if not self._model:
            return self._fallback.is_speech(audio)
        try:
            import torch  # type: ignore
            tensor = torch.from_numpy(audio).float()
            prob = float(self._model(tensor, 16000).item())
            return prob >= self.threshold
        except Exception:
            return self._fallback.is_speech(audio)
