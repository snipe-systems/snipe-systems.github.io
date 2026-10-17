"""Entry point.

    voice-trader                     # interactive push-to-talk (paper by default)
    voice-trader --dry-run           # same, but every order goes to the paper broker
    voice-trader --demo              # scripted demo of the whole pipeline
    voice-trader --live              # real money (gated, see below)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
import time


def _live_gate(config: dict) -> None:
    """Live trading requires BOTH TRADING_MODE=live in .env AND typing LIVE."""
    mode = (config.get("mode") or os.environ.get("TRADING_MODE") or "paper").lower()
    if mode != "live":
        return
    env_mode = os.environ.get("TRADING_MODE", "").lower()
    if env_mode != "live":
        print("REFUSED: live mode requires TRADING_MODE=live in .env.")
        sys.exit(1)
    answer = input("Type LIVE to confirm real-money trading: ").strip()
    if answer != "LIVE":
        print("REFUSED: confirmation did not match. Exiting.")
        sys.exit(1)
    print("LIVE MODE ENABLED.")


def _build(args) -> object:
    from .core.config import load_config, load_env
    load_env()
    config = load_config(args.config)
    if args.mode:
        config["mode"] = args.mode
    _live_gate(config)

    from .core.logging import AuditLogger, _REDACT
    from .risk.engine import RiskConfig, RiskEngine
    from .parser.resolver import Resolver
    from .core.journal import Journal
    from .core.killswitch import KillSwitch
    from .broker.registry import build_broker

    # Redact secrets from all logs.
    _REDACT[:] = [v for v in (os.environ.get("ALPACA_API_KEY"),
                              os.environ.get("ALPACA_SECRET_KEY"),
                              os.environ.get("BINANCE_API_KEY"),
                              os.environ.get("BINANCE_SECRET_KEY")) if v]

    broker = build_broker(config, args.mode)
    risk = RiskEngine(RiskConfig.from_dict(config.get("risk", {})))
    resolver = Resolver(broker.symbol_universe() or None)

    tts_cfg = config.get("tts", {})
    speaker = None
    if tts_cfg.get("enabled", True) and not args.no_speak:
        from .tts.speaker import Speaker
        speaker = Speaker(enabled=True)

    from .core.session import TradingSession
    session = TradingSession(
        config=config,
        broker=broker,
        risk=risk,
        resolver=resolver,
        journal=Journal(config.get("journal", {}).get("path", "journal/trades.csv")),
        killswitch=KillSwitch(config.get("killswitch", {}).get("path", "config/killswitch")),
        log=AuditLogger(),
        speaker=speaker,
        voice_verifier=_build_verifier(config),
        mode=config.get("mode", "paper"),
    )
    return config, session, broker


def _build_verifier(config: dict):
    auth = config.get("voice_auth", {})
    if not auth.get("enabled", False):
        return None
    from .voice_auth.verify import SpeakerVerifier
    v = SpeakerVerifier(auth.get("model_dir", "config/voice_profile"),
                        float(auth.get("threshold", 0.55)))
    return v if v.available() else None


def _build_stt(config: dict):
    from .stt.whisper_stt import WhisperSTT
    stt_cfg = config.get("stt", {})
    return WhisperSTT(
        model_size=stt_cfg.get("model_size", "base"),
        device=stt_cfg.get("device", "auto"),
        compute_type=stt_cfg.get("compute_type", "auto"),
        language=stt_cfg.get("language"),
    )


def run_repl(config: dict, session) -> int:
    """Interactive loop: type a command (or press Enter to speak)."""
    print("=" * 60)
    print(f"voice-trader  mode={config.get('mode', 'paper')}  broker={config.get('active_broker', 'paper')}")
    print("Type a command as text, or press Enter to speak into the mic.")
    print("Emergency: 'stop trading' halts everything. Ctrl+C quits.")
    print("=" * 60)

    audio = config.get("audio", {})
    use_mic = audio.get("push_to_talk_key") not in (None, "")
    mic = stt = vad = None
    if use_mic:
        try:
            from .audio.mic import Microphone
            from .audio.vad import EnergyVAD
            mic = Microphone(sample_rate=int(audio.get("sample_rate", 16000)),
                             device=audio.get("device"))
            vad = EnergyVAD()
            stt = _build_stt(config)
            if not mic.available() or not (stt and stt.available()):
                print("Mic/STT unavailable (install voice-trader[audio] and [stt]); text input only.")
                mic = None
            else:
                print("Mic input ready. Press Enter to talk.")
        except Exception as e:  # noqa: BLE001
            print(f"Mic unavailable ({e}); text input only.")
            mic = None

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if raw:
            response = session.handle_utterance(raw, audio=None)
            print(f"  {response.state.value.upper():<12} {response}")
            continue

        if mic is None:
            print("(no mic; type a command instead)")
            continue

        print("  listening...")
        data = mic.record(max_seconds=float(audio.get("max_record_seconds", 15)),
                          silence_stop=float(audio.get("silence_stop_seconds", 1.2)), vad=vad)
        if data is None or len(data) < int(audio.get("sample_rate", 16000)) * 0.3:
            print("  (nothing heard)")
            continue
        try:
            res = stt.transcribe(data, int(audio.get("sample_rate", 16000)))
        except Exception as e:  # noqa: BLE001
            print(f"  transcription failed: {e}")
            continue
        print(f"  heard: {res.text!r} (conf={res.confidence:.2f})")
        if res.confidence < 0.3:
            print("  low confidence — please repeat.")
            continue
        response = session.handle_utterance(res.text, audio=data)
        print(f"  {response.state.value.upper():<12} {response}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voice-trader")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--mode", choices=["paper", "live"], default=None)
    parser.add_argument("--dry-run", action="store_true", help="force paper broker")
    parser.add_argument("--demo", action="store_true", help="run the scripted demo")
    parser.add_argument("--backtest", action="store_true", help="run the backtest/simulation harness")
    parser.add_argument("--json", action="store_true", help="JSON-lines in/out (headless, pipeable)")
    parser.add_argument("--serve", action="store_true", help="run the local HTTP API")
    parser.add_argument("--host", default=None, help="HTTP/WS API bind host")
    parser.add_argument("--port", type=int, default=None, help="HTTP API port")
    parser.add_argument("--ws-port", type=int, default=None, help="WebSocket port")
    parser.add_argument("--no-ws", action="store_true", help="disable the WebSocket server")
    parser.add_argument("--export", default=None, metavar="PATH", help="export journal to PATH (csv/json/xlsx by extension)")
    parser.add_argument("--no-speak", action="store_true", help="disable TTS")
    args = parser.parse_args(argv)

    if args.backtest:
        from .scripts.backtest_cli import main as backtest_main
        return backtest_main()

    if args.demo:
        from .scripts.demo_dryrun import run_demo
        return run_demo()

    if args.dry_run:
        args.mode = "paper"

    config, session, _broker = _build(args)

    if args.export:
        fmt = Path(args.export).suffix.lstrip(".").lower() or "json"
        session.journal.export(args.export, fmt)
        print(f"journal exported to {args.export}")
        return 0

    if args.serve:
        from .interop.http_api import serve as serve_http
        from .interop.auth import load_auth

        api_cfg = config.get("api", {})
        host = args.host or api_cfg.get("host", "127.0.0.1")
        port = args.port if args.port is not None else int(api_cfg.get("port", 8010))
        ws_port = args.ws_port if args.ws_port is not None else int(api_cfg.get("ws_port", 8011))

        auth_store = load_auth(config)
        if auth_store is not None:
            print(f"API auth enabled ({auth_store.count()} active key(s)).")

        ws_thread = None
        if not args.no_ws:
            from .interop.ws_server import WebSocketServer
            ws = WebSocketServer(session, host=host, port=ws_port,
                                 auth_store=auth_store)
            if ws.available():
                ws_thread = ws.start()
                print(f"WebSocket API listening on ws://{host}:{ws_port}")
            else:
                print("WebSocket disabled: install voice-trader[ws] to enable it.")

        serve_http(session, host=host, port=port, auth_store=auth_store)
        return 0

    if args.json:
        from .interop.json_mode import run_json_loop
        return run_json_loop(session)

    return run_repl(config, session)


if __name__ == "__main__":
    sys.exit(main())


def serve_main() -> int:
    return main(["--serve"] + sys.argv[1:])


def json_main() -> int:
    return main(["--json"] + sys.argv[1:])


def backtest_main() -> int:
    return main(["--backtest"] + sys.argv[1:])
