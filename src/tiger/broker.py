"""
Alpaca paper-trading order wrapper.
All order submission, position queries, and EOD cleanup go through here.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
)
from dotenv import load_dotenv

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _client() -> TradingClient:
    load_dotenv()
    return TradingClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )


# ── entry orders ────────────────────────────────────────────────────────────

def buy_limit(ticker: str, qty: int, limit_price: Decimal) -> str | None:
    """Submit a limit buy. Returns order ID."""
    client = _client()
    req = LimitOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        limit_price=float(limit_price),
    )
    try:
        order = client.submit_order(req)
        log.info("BUY LIMIT %s %d @ %.2f  order_id=%s", ticker, qty, float(limit_price), order.id)
        return str(order.id)
    except Exception as exc:
        log.error("BUY LIMIT failed %s %d @ %.2f: %s", ticker, qty, float(limit_price), exc)
        return None


def sell_short_limit(ticker: str, qty: int, limit_price: Decimal) -> str | None:
    """Submit a limit sell-short. Returns order ID or None on failure."""
    client = _client()
    req = LimitOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.SELL,
        type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        limit_price=float(limit_price),
    )
    try:
        order = client.submit_order(req)
        log.info("SELL SHORT LIMIT %s %d @ %.2f  order_id=%s", ticker, qty, float(limit_price), order.id)
        return str(order.id)
    except Exception as exc:
        log.error("SELL SHORT failed %s %d @ %.2f: %s", ticker, qty, float(limit_price), exc)
        return None


# ── exit orders ─────────────────────────────────────────────────────────────

def close_position_market(ticker: str) -> str | None:
    """Market-order exit for the full position. Returns order ID or None if no position."""
    client = _client()
    try:
        response = client.close_position(ticker)
        log.info("MARKET EXIT %s  order_id=%s", ticker, response.id)
        return str(response.id)
    except Exception as exc:
        log.warning("close_position %s failed: %s", ticker, exc)
        return None


def cancel_all_orders() -> None:
    """Cancel all open orders — called at EOD before flush."""
    client = _client()
    client.cancel_orders()
    log.info("All open orders cancelled.")


def close_all_positions() -> None:
    """Liquidate all positions at market — EOD flush / safety flatten."""
    client = _client()
    client.close_all_positions(cancel_orders=True)
    log.info("All positions closed.")


def list_open_positions() -> list[str]:
    """Return tickers of any currently-open positions (empty if flat)."""
    client = _client()
    try:
        return [p.symbol for p in client.get_all_positions()]
    except Exception as exc:
        log.warning("list_open_positions failed: %s", exc)
        return []


# ── position queries ─────────────────────────────────────────────────────────

def get_position(ticker: str) -> dict | None:
    """
    Returns {qty, avg_entry_price, unrealized_pl} or None if flat.
    """
    client = _client()
    try:
        pos = client.get_open_position(ticker)
        return {
            "qty": int(pos.qty),
            "avg_entry_price": Decimal(str(pos.avg_entry_price)),
            "unrealized_pl": Decimal(str(pos.unrealized_pl)),
        }
    except Exception:
        return None


def get_account_pnl() -> Decimal:
    """Realized + unrealized P&L for the day (approximation from equity change)."""
    client = _client()
    acct = client.get_account()
    # equity - last_equity approximates intraday P&L
    return Decimal(str(acct.equity)) - Decimal(str(acct.last_equity))
