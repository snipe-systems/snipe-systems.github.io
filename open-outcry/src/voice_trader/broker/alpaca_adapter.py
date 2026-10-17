"""Alpaca adapter for US stocks and options (paper or live).

Uses the Alpaca REST API directly via httpx (no hard SDK dependency). Keys are
read from environment variables only. Options contract resolution maps
(underlying, strike, type, expiry) to an OCC symbol via the contracts endpoint;
if that endpoint is unavailable it degrades gracefully rather than guessing.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import httpx

from ..parser.intent import Action, Command, OrderType, QuantityKind
from .base import AccountInfo, BrokerAdapter, BrokerError, BrokerResult, Execution, Quote
from ..risk.engine import Position


class AlpacaAdapter(BrokerAdapter):
    name = "alpaca"
    is_paper = True

    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 base_url: str | None = None, data_url: str | None = None,
                 paper: bool = True):
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self.paper = paper
        self.base_url = (base_url or "https://paper-api.alpaca.markets").rstrip("/")
        # Safety: when in paper mode, never route to a live endpoint even if a
        # live base_url was mistakenly supplied.
        if paper:
            self.base_url = "https://paper-api.alpaca.markets"
        self.data_url = (data_url or "https://data.alpaca.markets").rstrip("/")
        self.is_paper = paper
        if not self.api_key or not self.secret_key:
            raise BrokerError("Alpaca API key/secret not set (env ALPACA_API_KEY / ALPACA_SECRET_KEY)")

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def _get(self, path: str, **params) -> dict:
        try:
            r = httpx.get(f"{self.base_url}{path}", headers=self._headers(),
                          params=params, timeout=10.0)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise BrokerError(f"Alpaca request failed: {e}") from e

    def _post(self, path: str, json: dict) -> dict:
        try:
            r = httpx.post(f"{self.base_url}{path}", headers=self._headers(),
                           json=json, timeout=10.0)
            if r.status_code >= 400:
                raise BrokerError(f"Alpaca rejected order: {r.status_code} {r.text}")
            return r.json()
        except httpx.HTTPError as e:
            raise BrokerError(f"Alpaca request failed: {e}") from e

    # --- account / quotes ---------------------------------------------------

    def get_account(self) -> AccountInfo:
        acct = self._get("/v2/account")
        positions = self.get_positions()
        return AccountInfo(
            buying_power=float(acct.get("buying_power", 0)),
            positions=positions,
            open_orders=int(acct.get("open_order_count", 0) or 0),
            realized_pnl_today=float(acct.get("realized_pnl", 0) or 0),
            trades_today=0,
        )

    def get_positions(self) -> list[Position]:
        data = self._get("/v2/positions")
        out = []
        for p in data:
            out.append(Position(
                symbol=p["symbol"],
                quantity=float(p["qty"]),
                avg_price=float(p.get("avg_entry_price", 0) or 0),
                last_price=float(p.get("current_price", 0) or 0),
                asset_class="option" if "option" in str(p.get("asset_class", "")).lower() else "stock",
            ))
        return out

    def get_quote(self, symbol: str) -> Quote | None:
        try:
            r = httpx.get(f"{self.data_url}/v2/stocks/{symbol}/quotes/latest",
                          headers=self._headers(), timeout=10.0)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            q = r.json()["quote"]
            return Quote(
                symbol=symbol,
                last_price=float(q.get("ap") or q.get("bp") or 0),
                bid=float(q.get("bp") or 0),
                ask=float(q.get("ap") or 0),
                timestamp=time.time(),
            )
        except (httpx.HTTPError, KeyError, ValueError):
            return None

    # --- order submission ---------------------------------------------------

    def submit_order(self, command: Command, idempotency_key: str) -> BrokerResult:
        o = command.order
        if o is None:
            return BrokerResult(False, error="no order intent")

        symbol = self._order_symbol(o)
        side = "buy" if o.action == Action.BUY else "sell"
        qty = self._resolve_quantity(o, symbol)
        if qty is None or qty <= 0:
            return BrokerResult(False, error="could not resolve a positive quantity")

        body: dict = {
            "symbol": symbol,
            "qty": str(round(qty, 4)),
            "side": side,
            "type": o.order_type.value if o.order_type.value != "trailing_stop" else "trailing_stop",
            "time_in_force": "day",
            "client_order_id": idempotency_key,
        }
        if o.order_type == OrderType.LIMIT:
            body["limit_price"] = str(o.limit_price)
        elif o.order_type == OrderType.STOP:
            body["stop_price"] = str(o.stop_price)
        elif o.order_type == OrderType.STOP_LIMIT:
            body["stop_price"] = str(o.stop_price)
            body["limit_price"] = str(o.limit_price)

        resp = self._post("/v2/orders", body)
        return BrokerResult(True, message=resp.get("status", "accepted"), execution=Execution(
            order_id=str(resp.get("id", "")),
            symbol=symbol,
            side=side,
            quantity=qty,
            price=float(o.limit_price or 0),
            status=resp.get("status", "accepted"),
            idempotency_key=idempotency_key,
            raw=resp,
        ))

    def cancel_all_orders(self) -> BrokerResult:
        try:
            r = httpx.delete(f"{self.base_url}/v2/orders", headers=self._headers(), timeout=10.0)
            if r.status_code >= 400:
                return BrokerResult(False, error=r.text)
            return BrokerResult(True, message="all open orders cancelled")
        except httpx.HTTPError as e:
            return BrokerResult(False, error=str(e))

    def close_all_positions(self) -> BrokerResult:
        try:
            r = httpx.delete(f"{self.base_url}/v2/positions", headers=self._headers(), timeout=10.0)
            if r.status_code >= 400:
                return BrokerResult(False, error=r.text)
            return BrokerResult(True, message="all positions closed")
        except httpx.HTTPError as e:
            return BrokerResult(False, error=str(e))

    def market_status(self) -> str:
        try:
            clock = self._get("/v2/clock")
            if clock.get("is_open"):
                return "open"
            now = datetime.now(timezone.utc)
            nxt_close = clock.get("next_close")
            nxt_open = clock.get("next_open")
            # crude pre/after-hours heuristic using the session boundaries
            if nxt_close and nxt_open:
                return "afterhours" if now < nxt_open.replace(tzinfo=timezone.utc) else "closed"
            return "closed"
        except BrokerError:
            return "unknown"

    def symbol_universe(self) -> set[str]:
        try:
            assets = self._get("/v2/assets", status="active", asset_class="us_equity")
            return {a["symbol"] for a in assets[:10000]}
        except BrokerError:
            return set()

    def resolve_option_contract(self, underlying: str, strike: float,
                                option_type: str, expiry: str) -> str | None:
        try:
            r = httpx.get(
                f"{self.base_url}/v2/options/contracts",
                headers=self._headers(),
                params={
                    "underlying_symbols": underlying,
                    "strike_price_gte": str(strike),
                    "strike_price_lte": str(strike),
                    "type": option_type,
                    "expiration_date": expiry,
                },
                timeout=10.0,
            )
            r.raise_for_status()
            contracts = r.json().get("option_contracts", [])
            if contracts:
                return contracts[0]["symbol"]
            return None
        except (httpx.HTTPError, ValueError, KeyError):
            return None

    # --- internals ----------------------------------------------------------

    def _order_symbol(self, o) -> str:
        if o.option_leg:
            l = o.option_leg
            if l.expiry:
                occ = self.resolve_option_contract(l.underlying, l.strike,
                                                   l.option_type.value, l.expiry)
                if occ:
                    return occ
            # Fall back to a readable OCC-style symbol the API may reject.
            return f"{l.underlying}{l.expiry or '000000'}{l.option_type.value[0].upper()}{l.strike}"
        return o.symbol or ""

    def _resolve_quantity(self, o, symbol: str) -> float | None:
        if o.quantity_kind == QuantityKind.ALL:
            for p in self.get_positions():
                if p.symbol == symbol:
                    return abs(p.quantity)
            return None
        if o.quantity_kind == QuantityKind.PERCENT:
            for p in self.get_positions():
                if p.symbol == symbol:
                    return abs(p.quantity) * (o.quantity or 0.0)
            return None
        return o.quantity
