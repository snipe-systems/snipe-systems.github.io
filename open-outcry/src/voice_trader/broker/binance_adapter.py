"""Binance USDT-M futures adapter (testnet by default).

Signed REST via httpx + HMAC-SHA256. Keys come from environment variables.
Crypto perps trade 24/7, so market_status() reports "open" unless the API is
unreachable. Quantities are in base-asset units; "buy" opens/increases a long,
"sell" opens/increases a short (or reduces a long).

Only the testnet is supported by this project. Live keys are deliberately not
wired here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse

import httpx

from ..parser.intent import Action, Command, OrderType, QuantityKind
from .base import AccountInfo, BrokerAdapter, BrokerError, BrokerResult, Execution, Quote
from ..risk.engine import Position


class BinanceFuturesAdapter(BrokerAdapter):
    name = "binance"
    is_paper = True  # testnet == paper

    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 base_url: str | None = None, testnet: bool = True):
        self.api_key = api_key or os.environ.get("BINANCE_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("BINANCE_SECRET_KEY", "")
        self.testnet = testnet
        self.base_url = (base_url or "https://testnet.binancefuture.com").rstrip("/")
        if not self.api_key or not self.secret_key:
            raise BrokerError("Binance API key/secret not set (env BINANCE_API_KEY / BINANCE_SECRET_KEY)")

    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        qs = urllib.parse.urlencode(params)
        sig = hmac.new(self.secret_key.encode(), qs.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _get(self, path: str, **params) -> dict:
        signed = self._sign(params)
        try:
            r = httpx.get(f"{self.base_url}{path}", params=signed,
                          headers={"X-MBX-APIKEY": self.api_key}, timeout=10.0)
            if r.status_code >= 400:
                raise BrokerError(f"Binance error {r.status_code}: {r.text}")
            return r.json()
        except httpx.HTTPError as e:
            raise BrokerError(f"Binance request failed: {e}") from e

    def _post(self, path: str, **params) -> dict:
        signed = self._sign(params)
        try:
            r = httpx.post(f"{self.base_url}{path}", params=signed,
                           headers={"X-MBX-APIKEY": self.api_key}, timeout=10.0)
            if r.status_code >= 400:
                raise BrokerError(f"Binance rejected order {r.status_code}: {r.text}")
            return r.json()
        except httpx.HTTPError as e:
            raise BrokerError(f"Binance request failed: {e}") from e

    # --- account / quotes ---------------------------------------------------

    def get_account(self) -> AccountInfo:
        acct = self._get("/fapi/v1/account")
        positions = []
        for p in acct.get("positions", []):
            amt = float(p.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            symbol = p.get("symbol", "")
            positions.append(Position(
                symbol=symbol,
                quantity=amt,
                avg_price=float(p.get("entryPrice", 0) or 0),
                last_price=0.0,
                asset_class="crypto",
            ))
        return AccountInfo(
            buying_power=float(acct.get("totalWalletBalance", 0) or 0),
            positions=positions,
            open_orders=0,
            realized_pnl_today=0.0,
            trades_today=0,
        )

    def get_quote(self, symbol: str) -> Quote | None:
        try:
            r = httpx.get(f"{self.base_url}/fapi/v1/ticker/price",
                          params={"symbol": symbol}, timeout=10.0)
            if r.status_code >= 400:
                return None
            px = float(r.json().get("price", 0) or 0)
            return Quote(symbol=symbol, last_price=px, bid=px, ask=px, timestamp=time.time())
        except (httpx.HTTPError, ValueError):
            return None

    # --- order submission ---------------------------------------------------

    def submit_order(self, command: Command, idempotency_key: str) -> BrokerResult:
        o = command.order
        if o is None:
            return BrokerResult(False, error="no order intent")
        symbol = self._order_symbol(o)
        side = "BUY" if o.action == Action.BUY else "SELL"
        qty = self._resolve_quantity(o, symbol)
        if qty is None or qty <= 0:
            return BrokerResult(False, error="could not resolve a positive quantity")

        params: dict = {
            "symbol": symbol,
            "side": side,
            "quantity": f"{qty:.6f}",
            "newClientOrderId": idempotency_key,
        }
        if o.order_type == OrderType.MARKET:
            params["type"] = "MARKET"
        elif o.order_type == OrderType.LIMIT:
            params["type"] = "LIMIT"
            params["price"] = f"{o.limit_price}"
            params["timeInForce"] = "GTC"
        elif o.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            params["type"] = "STOP_MARKET"
            params["stopPrice"] = f"{o.stop_price}"

        resp = self._post("/fapi/v1/order", **params)
        return BrokerResult(True, message=resp.get("status", "NEW"), execution=Execution(
            order_id=str(resp.get("orderId", "")),
            symbol=symbol,
            side=side.lower(),
            quantity=qty,
            price=float(resp.get("avgPrice") or 0),
            status=resp.get("status", "NEW"),
            idempotency_key=idempotency_key,
            raw=resp,
        ))

    def cancel_all_orders(self) -> BrokerResult:
        try:
            self._delete("/fapi/v1/allOpenOrders")
            return BrokerResult(True, message="all open orders cancelled")
        except BrokerError as e:
            return BrokerResult(False, error=str(e))

    def close_all_positions(self) -> BrokerResult:
        try:
            acct = self.get_account()
            for p in acct.positions:
                side = "SELL" if p.quantity > 0 else "BUY"
                qty = abs(p.quantity)
                self._post("/fapi/v1/order", symbol=p.symbol, side=side,
                           type="MARKET", quantity=f"{qty:.6f}")
            return BrokerResult(True, message="all positions closed")
        except BrokerError as e:
            return BrokerResult(False, error=str(e))

    def market_status(self) -> str:
        return "open"  # crypto futures trade 24/7

    def _delete(self, path: str, **params) -> dict:
        signed = self._sign(params)
        try:
            r = httpx.delete(f"{self.base_url}{path}", params=signed,
                             headers={"X-MBX-APIKEY": self.api_key}, timeout=10.0)
            if r.status_code >= 400:
                raise BrokerError(f"Binance error {r.status_code}: {r.text}")
            return r.json()
        except httpx.HTTPError as e:
            raise BrokerError(f"Binance request failed: {e}") from e

    # --- internals ----------------------------------------------------------

    def _order_symbol(self, o) -> str:
        sym = (o.symbol or "").upper()
        if sym and not sym.endswith("USDT"):
            return sym + "USDT"
        return sym

    def _resolve_quantity(self, o, symbol: str) -> float | None:
        if o.quantity_kind == QuantityKind.ALL:
            for p in self.get_account().positions:
                if p.symbol == symbol:
                    return abs(p.quantity)
            return None
        if o.quantity_kind == QuantityKind.PERCENT:
            for p in self.get_account().positions:
                if p.symbol == symbol:
                    return abs(p.quantity) * (o.quantity or 0.0)
            return None
        return o.quantity
