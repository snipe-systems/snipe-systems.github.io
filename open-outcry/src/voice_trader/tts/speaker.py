"""Local text-to-speech (pyttsx3). Optional; disabled via config.

Runs speak() on a worker thread so audio feedback never blocks the pipeline.
"""

from __future__ import annotations

import threading


class Speaker:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._engine = None
        self._lock = threading.Lock()
        if enabled:
            self._init_engine()

    def _init_engine(self) -> None:
        try:
            import pyttsx3  # noqa: WPS433 (optional dependency)
            self._engine = pyttsx3.init()
        except Exception:
            self._engine = None

    def speak(self, text: str) -> None:
        if not self.enabled or not self._engine:
            return
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        try:
            with self._lock:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            pass
