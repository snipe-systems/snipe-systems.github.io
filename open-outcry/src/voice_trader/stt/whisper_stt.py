"""Local Whisper transcription via faster-whisper.

Returns both the text and a confidence estimate (from the no-speech probability
and log-probability of the decoded segments). Low confidence is the signal the
pipeline uses to re-ask instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class STTResult:
    text: str
    confidence: float
    language: str = ""


class WhisperSTT:
    def __init__(self, model_size: str = "base", device: str = "auto",
                 compute_type: str = "auto", language: str | None = None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError("faster-whisper is not installed (pip install voice-trader[stt])") from e
        self._model = WhisperModel(self.model_size, device=self.device,
                                   compute_type=self.compute_type)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> STTResult:
        self._load()
        audio = np.asarray(audio, dtype=np.float32)
        segments, info = self._model.transcribe(
            audio, language=self.language, beam_size=5,
            vad_filter=False, condition_on_previous_text=False,
        )
        parts: list[str] = []
        confs: list[float] = []
        for seg in segments:
            parts.append(seg.text.strip())
            no_speech = getattr(seg, "no_speech_prob", 0.5) or 0.5
            logprob = getattr(seg, "avg_logprob", 0.0) or 0.0
            conf = (1.0 - no_speech) * max(0.0, min(1.0, np.exp(logprob)))
            confs.append(conf)

        text = " ".join(parts).strip()
        confidence = float(np.mean(confs)) if confs else 0.0
        return STTResult(text=text, confidence=confidence, language=getattr(info, "language", ""))
