"""Speaker verification using local SpeechBrain ECAPA-TDNN embeddings.

Enrollment stores an averaged embedding per speaker under `model_dir`. Verify()
returns (matched, cosine_similarity) against the stored profiles. This is the
"only my voice places trades" guarantee; it never phones home.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class SpeakerVerifier:
    def __init__(self, model_dir: str | Path = "config/voice_profile",
                 threshold: float = 0.55):
        self.model_dir = Path(model_dir)
        self.threshold = threshold
        self._classifier = None
        self._load_error: str | None = None
        self._profiles = self._load_profiles()

    # --- profile management -------------------------------------------------

    def _load_profiles(self) -> dict[str, np.ndarray]:
        profiles: dict[str, np.ndarray] = {}
        if not self.model_dir.exists():
            return profiles
        for f in self.model_dir.glob("*.npy"):
            profiles[f.stem] = np.load(f)
        return profiles

    def enrolled_speakers(self) -> list[str]:
        return list(self._profiles.keys())

    def enroll(self, audio: np.ndarray, name: str = "default") -> float:
        """Enroll (or reinforce) a speaker profile. Returns the stored vector count."""
        emb = self._embed(audio)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        path = self.model_dir / f"{name}.npy"
        if path.exists():
            existing = np.load(path)
            emb = (existing + emb) / 2.0
        np.save(path, emb)
        self._profiles[name] = emb
        return len(self._profiles)

    def available(self) -> bool:
        return bool(self._profiles)

    # --- verification -------------------------------------------------------

    def verify(self, audio: np.ndarray) -> tuple[bool, float]:
        if not self._profiles:
            return False, 0.0
        emb = self._embed(audio)
        best_name, best = None, -1.0
        for name, profile in self._profiles.items():
            sim = self._cosine(emb, profile)
            if sim > best:
                best, best_name = sim, name
        return best >= self.threshold, float(best)

    # --- internals ----------------------------------------------------------

    def _load_classifier(self) -> bool:
        if self._classifier is not None:
            return True
        if self._load_error is not None:
            return False
        try:
            from speechbrain.inference.speaker import EncoderClassifier
            self._classifier = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=str(self.model_dir / "_cache"),
            )
            return True
        except Exception as e:  # noqa: BLE001
            self._load_error = str(e)
            return False

    def _embed(self, audio: np.ndarray) -> np.ndarray:
        if not self._load_classifier():
            raise RuntimeError(
                "speaker model unavailable (pip install voice-trader[speaker]): "
                + (self._load_error or "unknown"))
        try:
            import torch
        except ImportError as e:
            raise RuntimeError("torch is required for speaker verification") from e
        x = np.asarray(audio, dtype=np.float32).reshape(1, -1)
        tensor = torch.from_numpy(x)
        with torch.no_grad():
            emb = self._classifier.encode_batch(tensor).squeeze().cpu().numpy()
        return emb

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        a = a / (np.linalg.norm(a) + 1e-9)
        b = b / (np.linalg.norm(b) + 1e-9)
        return float(np.dot(a, b))
