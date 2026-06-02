"""
Event logger — writes every decision to data/live_log.jsonl.
The dashboard reads this file to display live state.
Each line is one JSON event with a type + timestamp + payload.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
LOG_PATH = Path(__file__).parents[2] / "data" / "live_log.jsonl"


def _write(event_type: str, payload: dict) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    record = {
        "type": event_type,
        "ts": datetime.now(ET).isoformat(),
        **payload,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── scanner events ───────────────────────────────────────────────────────────

def log_scan(candidates: list[dict]) -> None:
    _write("scan", {"candidates": candidates})


def log_no_candidates() -> None:
    _write("scan", {"candidates": []})


# ── bar events (throttled — only log when something interesting happens) ─────

def log_indicators(ticker: str, bar_time: str, ind: dict) -> None:
    _write("indicators", {"ticker": ticker, "bar_time": bar_time, "ind": ind})


# ── trade events ─────────────────────────────────────────────────────────────

def log_entry(ticker: str, direction: str, qty: int, limit_price: float,
              stop_price: float, strike_num: int, full_size: bool,
              ind: dict, reason: str = "") -> None:
    _write("entry", {
        "ticker": ticker,
        "direction": direction,
        "qty": qty,
        "limit_price": limit_price,
        "stop_price": stop_price,
        "strike_num": strike_num,
        "full_size": full_size,
        "ind": ind,
        "reason": reason,
    })


def log_exit(ticker: str, direction: str, exit_price: float,
             entry_price: float, qty: int, pnl: float,
             reason: str, daily_pnl: float) -> None:
    _write("exit", {
        "ticker": ticker,
        "direction": direction,
        "exit_price": exit_price,
        "entry_price": entry_price,
        "qty": qty,
        "pnl": pnl,
        "reason": reason,
        "daily_pnl": daily_pnl,
    })


def log_ratchet(ticker: str, direction: str, old_stop: float,
                new_stop: float, alarm: str) -> None:
    _write("ratchet", {
        "ticker": ticker,
        "direction": direction,
        "old_stop": old_stop,
        "new_stop": new_stop,
        "alarm": alarm,
    })


def log_scale_in(ticker: str, direction: str, add_qty: int,
                 blended_price: float, new_stop: float) -> None:
    _write("scale_in", {
        "ticker": ticker,
        "direction": direction,
        "add_qty": add_qty,
        "blended_price": blended_price,
        "new_stop": new_stop,
    })


def log_circuit_break(ticker: str, daily_pnl: float) -> None:
    _write("circuit_break", {"ticker": ticker, "daily_pnl": daily_pnl})


def log_eod(tickers: list[str], daily_pnl: float) -> None:
    _write("eod", {"tickers": tickers, "daily_pnl": daily_pnl})


# ── reader (used by dashboard) ───────────────────────────────────────────────

def read_today() -> list[dict]:
    """Return all events from today's log file."""
    if not LOG_PATH.exists():
        return []
    today = datetime.now(ET).date().isoformat()
    events = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("ts", "").startswith(today):
                    events.append(ev)
            except json.JSONDecodeError:
                continue
    return events


def read_all() -> list[dict]:
    """Return all events ever logged."""
    if not LOG_PATH.exists():
        return []
    events = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events
