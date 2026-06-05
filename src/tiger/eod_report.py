"""
End-of-day reconciliation.

Runs after the close. Pulls the REAL Alpaca results for the day (filled orders,
account P&L) and appends one permanent record to data/track_record.jsonl.

This is the sample that actually matters: real fills, not the engine's
limit-price estimates. Over weeks this builds the 200+ trade record we need to
judge whether the strategy has edge net of real costs.

It does NOT change any strategy rule. It only records the truth.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest
from dotenv import load_dotenv

ET = ZoneInfo("America/New_York")
TRACK_PATH = Path(__file__).parents[2] / "data" / "track_record.jsonl"


def _client() -> TradingClient:
    load_dotenv()
    return TradingClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )


def reconcile_today() -> dict:
    """Pull real fills + account P&L for today, append to the track record."""
    client = _client()
    now = datetime.now(ET)
    today = now.date()
    session_open = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Real filled orders today
    orders = client.get_orders(GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        after=session_open,
        limit=500,
    ))
    fills = [o for o in orders if str(o.status) == "OrderStatus.FILLED"
             and o.filled_qty and float(o.filled_qty) > 0]

    buys = [o for o in fills if str(o.side) == "OrderSide.BUY"]
    sells = [o for o in fills if str(o.side) == "OrderSide.SELL"]

    account = client.get_account()
    day_pnl = Decimal(str(account.equity)) - Decimal(str(account.last_equity))

    record = {
        "date": today.isoformat(),
        "real_day_pnl": float(day_pnl),
        "equity_close": float(account.equity),
        "fills_total": len(fills),
        "buys": len(buys),
        "sells": len(sells),
        "scope": os.getenv("ALARM_D_SCOPE", "session"),
        "recorded_at": now.isoformat(),
    }

    TRACK_PATH.parent.mkdir(exist_ok=True)
    # Don't double-record the same day — overwrite if today already present
    existing = []
    if TRACK_PATH.exists():
        for line in TRACK_PATH.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get("date") != today.isoformat():
                    existing.append(line)
            except json.JSONDecodeError:
                continue
    existing.append(json.dumps(record))
    TRACK_PATH.write_text("\n".join(existing) + "\n")
    return record


def load_track_record() -> list[dict]:
    if not TRACK_PATH.exists():
        return []
    out = []
    for line in TRACK_PATH.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def summary() -> str:
    records = load_track_record()
    if not records:
        return "No track record yet."
    total = sum(r["real_day_pnl"] for r in records)
    green = sum(1 for r in records if r["real_day_pnl"] > 0)
    n = len(records)
    lines = [
        "=" * 52,
        "  TIGER SOVEREIGN — REAL TRACK RECORD (paper)",
        "=" * 52,
        f"  Trading days recorded : {n}",
        f"  Green days            : {green} ({green/n*100:.0f}%)",
        f"  Cumulative real P&L   : ${total:+,.2f}",
        f"  Avg per day           : ${total/n:+,.2f}",
        "-" * 52,
    ]
    for r in records[-10:]:
        lines.append(f"  {r['date']}  ${r['real_day_pnl']:+9,.2f}  "
                     f"({r['fills_total']} fills, {r['scope']} scope)")
    lines.append("=" * 52)
    lines.append("  NOTE: paper fills, no slippage/borrow fees. Need 200+")
    lines.append("  trades across varied regimes before trusting edge.")
    return "\n".join(lines)


if __name__ == "__main__":
    rec = reconcile_today()
    print(f"Recorded {rec['date']}: real P&L ${rec['real_day_pnl']:+,.2f} "
          f"({rec['fills_total']} fills)")
    print()
    print(summary())
