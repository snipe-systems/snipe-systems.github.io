"""Headless JSON-lines interface for driving voice-trader from other software.

Reads JSON objects (one per line) on stdin and writes JSON responses (one per
line) on stdout. Any line that is not valid JSON is treated as raw command text,
so a plain `printf "buy 10 AAPL at 230\n" | voice-trader --json` also works.

Input:  {"text": "buy 10 AAPL at 230"}
Output: {"text": "...", "state": "confirming", "executed": false,
         "blocked": false, "pending_confirmation": true}
"""

from __future__ import annotations

import json
import sys

from ..core.session import Response, TradingSession


def response_to_dict(r: Response) -> dict:
    return {
        "text": r.text,
        "state": r.state.value,
        "executed": r.executed,
        "blocked": r.blocked,
        "pending_confirmation": r.pending_confirmation,
    }


def run_json_loop(session: TradingSession,
                  input_stream=None, output_stream=None) -> int:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout

    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            req = {"text": line}

        if not isinstance(req, dict):
            req = {"text": str(req)}

        text = str(req.get("text") or req.get("command") or "").strip()
        if text.lower() in ("__exit__", "exit", "quit", "shutdown"):
            break

        resp = session.handle_utterance(text, audio=None)
        out = response_to_dict(resp)
        if resp.executed:
            acct = session.broker.get_account()
            out["positions"] = {p.symbol: p.quantity for p in acct.positions}
            out["realized_pnl"] = acct.realized_pnl_today
        output_stream.write(json.dumps(out) + "\n")
        output_stream.flush()

    return 0
