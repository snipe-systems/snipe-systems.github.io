"""Audit logger: every transcript, parse, validation, confirm, fill and
rejection goes to a timestamped local file."""

from __future__ import annotations

import logging
import time
from pathlib import Path

_REDACT: list[str] = []  # secret substrings redacted from all log output


class AuditLogger:
    def __init__(self, log_dir: str | Path = "logs", name: str = "voice-trader"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.log_dir / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.log"

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

        fh = logging.FileHandler(self._file)
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        self.logger.addHandler(sh)

    def _clean(self, msg: str) -> str:
        if _REDACT:
            for secret in _REDACT:
                msg = msg.replace(secret, "[REDACTED]")
        return msg

    def event(self, kind: str, **fields) -> None:
        parts = [f"{k}={v}" for k, v in fields.items()]
        self.logger.info("[%s] %s", kind, self._clean(" ".join(parts)))

    def transcript(self, text: str) -> None:
        self.logger.info("[transcript] %r", self._clean(text))

    def debug(self, msg: str) -> None:
        self.logger.debug(self._clean(msg))

    def error(self, msg: str) -> None:
        self.logger.error(self._clean(msg))
