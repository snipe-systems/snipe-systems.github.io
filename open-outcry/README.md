# voice-trader

A voice-controlled trading execution tool with **hard safety guarantees**.
Paper-first, position-aware, options-fluent, and voice-authenticated.

The whole pipeline is:

```
speak → transcribe (local Whisper) → parse → resolve symbol → validate risk
      → spoken read-back → explicit "confirm" → execute → journal (CSV)
```

No order ever executes without a spoken read-back **and** the word "confirm".
Paper trading is the default; live trading is deliberately hard to turn on.

---

## 1. Safety model (read this first)

| Rule | How it's enforced |
|---|---|
| Paper by default | `mode: paper` in config. Live needs `TRADING_MODE=live` in `.env` **and** typing `LIVE` at startup. |
| No trade without confirmation | Hard-coded `ConfirmationGate`. Only an utterance containing `confirm` (and no negation) advances to execution. `yeah`, silence, or anything else = no trade. |
| Limits enforced in code | `risk/engine.py` blocks on `max_order_value`, `max_position_per_symbol`, `max_daily_loss`, `max_trades_per_day`, `max_open_orders`. Checked **before** confirm **and** before execution. |
| Kill switch | Say "stop trading", or create the kill-switch file (`config/killswitch`, any content). Halts execution until restart. |
| Never guess | Low-confidence or missing fields → the tool asks. Ambiguous symbols (SPY/SPX) → flagged with "Did you mean …?" and still require confirm. |
| Idempotency | One voice command = at most one order. Content-hash signature + rolling window blocks repeats (mic glitch, double-speak). |
| Secrets | Keys only from `.env`/env vars. Redacted from all logs. `.env` is gitignored. |

---

## 2. Install

Requires Python 3.10+.

```bash
cd voice-trader
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .

# Core runtime (text input, paper broker, parser, risk, journal):
pip install -e .              # httpx, pyyaml, python-dotenv, numpy

# Voice + speech (add what you need):
pip install -e ".[audio]"     # microphone capture + VAD
pip install -e ".[stt]"       # local Whisper (faster-whisper)
pip install -e ".[speaker]"   # speaker verification (speechbrain + torch)
pip install -e ".[tts]"       # audio read-back

# Or everything at once:
pip install -e ".[all,test]"
```

You can run the full pipeline **without any microphone, GPU, or broker API**
using the paper broker and text input. Only the `audio`/`stt`/`speaker`/`tts`
extras need optional hardware/deps.

---

## 3. Configure

### Secrets — `.env`

```bash
cp .env.example .env
```

```env
TRADING_MODE=paper            # paper | live

# Alpaca (stocks + options) — paper keys only to start
ALPACA_API_KEY=
ALPACA_SECRET_KEY=

# Binance futures testnet (crypto perps) — testnet keys only
BINANCE_API_KEY=
BINANCE_SECRET_KEY=

VOICE_AUTH_ENABLED=0          # set to 1 after enrollment
VOICE_AUTH_REQUIRED=0         # 1 = refuse execution unless voice matches
```

### Risk + broker — `config/config.yaml`

```yaml
mode: paper                  # paper | live
active_broker: paper         # paper | alpaca | binance

risk:
  max_order_value: 5000.0
  max_position_per_symbol: 10000.0
  max_daily_loss: 500.0
  max_trades_per_day: 25
  emergency_confirm: true     # flatten/cancel still need one "confirm"
  duplicate_window_seconds: 300
  price_stale_tolerance_pct: 2.0
  require_market_open: true
```

`emergency_confirm: false` makes "flatten everything" / "cancel everything"
execute instantly with no confirmation — faster, but a stray word could wipe
positions. **Leave it `true` unless you know why.**

---

## 4. Run

```bash
# Interactive (paper by default). Type commands as text, or press Enter to speak.
voice-trader

# Force paper / simulation even if config says otherwise
voice-trader --dry-run

# Scripted dry-run demo: every step printed, no real orders, auto-confirm shown
voice-trader --demo

# Live (REAL MONEY) — requires TRADING_MODE=live in .env AND typing LIVE
voice-trader --live
```

First run without a mic/STT: just type commands (e.g. `buy 10 AAPL at 230`).

### Speak / listen

Push-to-talk is the safest and default input mode. With `audio`/`stt` extras
installed, press Enter (or the configured hotkey) to record; release/silence
stops the capture, transcription runs locally, and the order is read back.

---

## 5. Voice authentication (only YOUR voice trades)

```bash
voice-trader-enroll
```

Records ~5 short phrases and stores an averaged speaker embedding locally
(`config/voice_profile/`). Then in `.env` set:

```env
VOICE_AUTH_ENABLED=1
VOICE_AUTH_REQUIRED=1
```

With `required=1`, execution is refused unless the enrolled speaker matches;
queries ("what's my delta") still work for anyone. This protects against a TV,
a visitor, or a recording triggering an order. Enrollment is optional and
per-user — leave it off until you enroll.

---

## 6. Commands

| Say | Does |
|---|---|
| `buy 10 shares of Apple at 230` | limit order (name → ticker mapping built in) |
| `buy 10 AAPL at market` | market order |
| `buy 10 AAPL at 230, stop at 225, target 240` | bracket (entry + stop + target) in one command |
| `sell half my Tesla position` | reduce by 50% |
| `close my SPY put` | close existing option (matched to your position) |
| `buy 5 SPY 770 puts expiring this Friday` | options, expiry shorthand |
| `sell my QQQ 0DTE calls` | `0DTE` = same-day |
| `buy the SPY 760/770 put spread` | vertical spread |
| `move my stop on SPY to 760` | adjust stop |
| `what's my delta` / `what are my positions` | query (read-only) |
| `tag this pullback-RS` | tag last journal entry with strategy |
| `cancel all orders` / `flatten everything` | emergency (confirm-gated by default) |
| `stop trading` | kill switch (voice) |

Expiry shorthand: `this Friday`, `next Friday`, `0DTE`, `today`, `this week`,
`next week`, `Nov 20`, `November 20th`, `11/20`.

---

## 7. Test

```bash
pytest
```

- `tests/test_parser.py` — stocks, numbers (`fifteen` vs `fifty`), brackets
- `tests/test_options_parsing.py` — strikes, expiries, spreads + leg direction
- `tests/test_validation.py` — resolver ambiguity + every risk limit
- `tests/test_confirmation.py` — the gate: only `confirm` advances
- `tests/test_session.py` — end-to-end against the paper broker
- `tests/test_risk_edge.py` — boundary values (exactly at / just over each limit)
- `tests/test_backtest.py` — replay fills, stale-price re-quote, limit
  marketability, realized P&L
- `tests/test_fuzz_parser.py` — 12,000+ randomized/mutated/garbage inputs: the
  parser and session never crash, and random input never executes
- `tests/test_api.py` — the public Python API, driven as external software would

### Stress test (the pass bar)

```bash
python tests/stress_test.py
```

27 tricky commands: SPY vs SPX, `fifteen` vs `fifty`, noise, half-heard
commands, and a command spoken while another is still confirming. The pass bar
is **zero wrong executions** — the script prints a table and exits non-zero if
any command mis-executes.

### Backtest / simulation

```bash
voice-trader-backtest --scenario jump      # stale-price re-confirm demo
voice-trader-backtest --scenario random    # random-walk fills + P&L
voice-trader-backtest --script cmds.txt    # your own script
```

Replays a command script against a price feed through the **full** pipeline
(parse → validate → confirm → execute → journal) and prints an audit report:
per-command fills/blocks, realized P&L, cash, and final positions. Price feeds
support random walks, single sharp jumps, or real historical CSV
(`backtest.price_feed.from_csv`). Fills are realistic — market orders fill at
the tick, limit orders only if marketable, non-marketable limits are rejected.

---

## 7b. Interop — use it from anything

`voice-trader` is designed to be embedded and driven by other software, not
just used as a standalone CLI. Five surfaces:

### 1. Python library API

```python
from voice_trader import create_session, run_command

session = create_session(seed_positions={"TSLA": 20.0}, prices={"TSLA": 300.0})
run_command(session, "buy 10 shares of Apple at 230")   # -> pending confirmation
resp = run_command(session, "confirm")                   # -> Filled. buy 10 AAPL
session.journal.read()                                   # plain CSV for your tools
```

Exposes `TradingSession`, `Response`, `parse`, `Resolver`, `RiskEngine`,
`PaperBroker`, `Journal`, `KillSwitch`, the intent model, data providers, and
journal sinks. Bring your own broker via `BrokerAdapter`, your own prices via
`MarketDataProvider`.

### 2. Headless JSON mode (stdin/stdout)

```bash
printf '{"text":"buy 10 AAPL at 230"}\n{"text":"confirm"}\n' | voice-trader --json
```

Reads JSON lines, writes JSON lines (`state`, `executed`, `blocked`,
`pending_confirmation`, plus positions/P&L on fills). Non-JSON input lines are
treated as raw command text, so simple pipes work too.

### 3. Local HTTP API

```bash
voice-trader --serve --host 127.0.0.1 --port 8010
```

```
POST /command  {"text":"buy 10 AAPL at 230"}
POST /confirm   POST /cancel   POST /halt
GET  /health    GET /state    GET /positions    GET /journal
```

Stdlib-only, binds 127.0.0.1 by default. Any HTTP client (curl, a dashboard,
another service) can drive it.

### 3b. WebSocket API (real-time, bidirectional)

```bash
pip install voice-trader[ws]
voice-trader --serve        # HTTP + WebSocket (ws://127.0.0.1:8011)
```

Clients send `{"text": "..."}` commands and receive `response` messages, plus
streamed `event` messages (transcript, pending, filled, blocked, halted) as they
happen. Protocol:

```
client -> server   {"text": "buy 10 AAPL at 230"}
                   {"type": "auth", "key": "..."}          # first msg, if auth on
server -> client   {"type": "response", "text": ..., "state": ..., ...}
                   {"type": "event", "event": {...}}       # streamed lifecycle events
```

### 3c. API keys (auth the HTTP + WebSocket APIs)

Keys are generated once and stored **hashed** (never plaintext); the plaintext is
shown exactly once at creation. Enforcement is off by default.

```bash
voice-trader-key create --label "my-dashboard"    # prints the key ONCE
voice-trader-key list                             # labels + prefixes + status
voice-trader-key revoke <prefix>                  # revoke a key
```

Turn enforcement on in `config/config.yaml`:

```yaml
api:
  require_auth: true
  key_file: "config/api_keys.json"
```

Then clients authenticate with `Authorization: Bearer <key>` (HTTP) or
`{"type":"auth","key":"<key>"}` (WebSocket). When auth is on and no keys exist,
`voice-trader --serve` prints a warning and all requests are refused until you
create one.

### 4. Custom data feeds

```python
from voice_trader import create_session, StaticProvider, CsvMarketDataProvider, DataProviderBroker

provider = CsvMarketDataProvider("prices.csv")        # or StaticProvider({...})
session = create_session(broker=DataProviderBroker(provider))
```

Implement `MarketDataProvider.quote(symbol) -> Quote` to feed prices from any
source (your API, DB, feed).

### 5. Journal export (CSV / JSON / xlsx)

```bash
voice-trader --export trades.json     # or .csv / .xlsx (xlsx needs openpyxl)
```

Or in code: `Journal(csv, json_path=..., xlsx_path=...)` mirrors every trade to
multiple formats at once. The CSV columns (`timestamp, symbol, action, quantity,
fill_price, strategy, idempotency_key`) import into TradingView/Excel/spreadsheets.

### Docker / CI

```bash
docker build -t voice-trader .
docker run --rm -p 8010:8010 voice-trader     # HTTP API, paper mode
```

All settings are overridable via environment variables (`VOICE_TRADER_MODE`,
`VOICE_TRADER__RISK__MAX_ORDER_VALUE`, …) so containers/CI can configure it
without editing files. `.github/workflows/ci.yml` runs the full test suite,
stress test, backtest, demo, and JSON smoke on every push.

Optional deps (audio, Whisper, speaker verification, TTS, live broker SDKs) load
lazily — the paper/text/HTTP/JSON path needs only `httpx`, `pyyaml`,
`python-dotenv`, and `numpy`.

---

## 8. Failure modes

| Scenario | What happens |
|---|---|
| Mic drops / no audio | Recording returns nothing; the session stays idle and says "nothing heard". No order. |
| Broker API down | `BrokerError` is caught; the order is reported as rejected, the gate clears, and nothing is submitted. Logged. |
| Half-heard / low-confidence transcript | Confidence below threshold → "please repeat". Missing fields → targeted questions ("how many?", "which strike?"). Never guessed. |
| Ambiguous symbol (SPY vs SPX) | "Did you mean SPX?" in the read-back; still requires confirm. |
| Price moves after read-back | Re-quoted at execution; if drift exceeds `price_stale_tolerance_pct`, it re-asks for confirm at the new price. |
| Repeated command / mic glitch | Idempotency + duplicate guard block a second identical order in the window. |
| Market closed | `require_market_open` blocks execution and says so. |
| Kill-switch file appears | Execution halts immediately; only removal + restart resumes. |
| Speaker mismatch (voice auth) | Execution refused; read-only queries still answered. |

---

## 9. Security notes

- Secrets live only in `.env` (gitignored) or real environment variables.
- All logs redact the configured API keys/secrets.
- Nothing is sent anywhere except the broker's own API, and only when an order
  is confirmed.
- Local Whisper and local speaker verification mean your voice never leaves the
  machine.

---

## 10. Architecture

```
src/voice_trader/
├── main.py               # CLI entry, interactive loop, live-mode gate
├── api.py                # public Python API (import-driven usage)
├── interop/              # JSON mode, HTTP API, pluggable journal sinks
├── data/                 # MarketDataProvider + static/CSV/streaming feeds
├── audio/                # mic capture (PTT) + VAD
├── stt/                  # local Whisper transcription
├── voice_auth/           # enroll + verify (ECAPA speaker embeddings)
├── parser/               # intent model, rule parser, options language, resolver
├── risk/                 # limits, duplicate/idempotency guard
├── broker/               # base ABC + paper / alpaca / binance adapters + registry
├── backtest/             # price feed + replay broker + backtest runner
├── core/                 # session orchestrator, confirmation gate, kill switch,
│                         # journal, audit log, market/session, pricing (delta)
└── tts/                  # local text-to-speech (optional)
```

The broker is swappable via `active_broker` in config. `paper` is a fully local
simulator; `alpaca` covers stocks + options; `binance` covers crypto perps
(testnet).

---

## 11. Known limitations / deliberate choices

- **Options premium modeling** (paper mode): fills use a nominal premium or the
  limit price; risk uses limit price for notional. Real premium checks are the
  broker's responsibility in live mode.
- **Spreads** follow the standard debit/credit convention (buy put spread = buy
  higher strike, sell lower strike). Legs are listed in the read-back; confirm
  carefully.
- **`move stop`** is simulated in paper mode (logged, not routed) and is
  broker-dependent in live mode.
- **Confusable tickers** (SPY/SPX, GOOG/GOOGL, IWM/DIA, BTC/ETH) always get a
  "Did you mean …?" caution before confirmation. This is deliberate — a wrong
  symbol is the most expensive mistake the tool could make.
- The parser is **deterministic and rule-based** — no LLM in the execution path.
  It covers the command set above; novel phrasings may fall back to "please
  repeat" rather than guess.

---

## 12. Legal

Educational tooling. Paper trade first. Nothing here is financial advice.
