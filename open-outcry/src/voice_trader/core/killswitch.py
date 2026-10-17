"""Kill switch: voice command + a watched file.

If the file at `killswitch.path` exists (any content), the session halts
execution immediately and refuses new orders until the file is removed and the
session is restarted.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


class KillSwitch:
    def __init__(self, path: str | Path, poll_seconds: float = 0.2):
        self.path = Path(path)
        self.poll_seconds = poll_seconds
        self._voice_halt = False
        self._file_halt = False

    def trigger_voice(self) -> None:
        self._voice_halt = True

    def reset_voice(self) -> None:
        self._voice_halt = False

    def file_triggered(self) -> bool:
        return self.path.exists()

    def is_halted(self) -> bool:
        return self._voice_halt or self.file_triggered()

    def raise_file(self) -> None:
        """Create the kill-switch file (used by tests and external tools)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"halted at {time.time()}\n")

    def clear_file(self) -> None:
        if self.path.exists():
            self.path.unlink()
