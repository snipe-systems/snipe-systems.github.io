"""Trade journal: append-only, writes to one or more pluggable sinks.

Defaults to CSV for backward compatibility, but can mirror to JSON Lines and/or
XLSX at the same time by passing `json_path`/`xlsx_path` (or explicit `sinks`).
"""

from __future__ import annotations

import time
from pathlib import Path

from ..interop.journal_sink import (
    CsvSink,
    JournalSink,
    JsonLinesSink,
    XlsxSink,
)


class Journal:
    def __init__(self, path: str | Path | None = None, *,
                 json_path: str | Path | None = None,
                 xlsx_path: str | Path | None = None,
                 sinks: list[JournalSink] | None = None):
        self.sinks: list[JournalSink] = list(sinks or [])
        if path:
            self.sinks.append(CsvSink(path))
        if json_path:
            self.sinks.append(JsonLinesSink(json_path))
        if xlsx_path:
            self.sinks.append(XlsxSink(xlsx_path))
        if not self.sinks:
            self.sinks.append(CsvSink("journal/trades.csv"))

        self.path = self.sinks[0].path if hasattr(self.sinks[0], "path") else None

    def log(self, *, symbol: str, action: str, quantity: float, fill_price: float,
            strategy: str = "", idempotency_key: str = "") -> None:
        row = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "fill_price": fill_price,
            "strategy": strategy,
            "idempotency_key": idempotency_key,
        }
        for sink in self.sinks:
            sink.write(row)

    def tag_last(self, tag: str) -> bool:
        ok = False
        for sink in self.sinks:
            ok = sink.tag_last(tag) or ok
        return ok

    def read(self) -> list[dict]:
        """Read from the primary (first) sink."""
        return self.sinks[0].read()

    def read_all(self) -> dict[str, list[dict]]:
        return {type(s).__name__: s.read() for s in self.sinks}

    def export(self, path: str | Path, fmt: str = "json") -> None:
        """One-off export of the journal to a file in the given format."""
        from ..interop.journal_sink import build_sink
        sink = build_sink(path, fmt)
        for row in self.read():
            sink.write(row)
