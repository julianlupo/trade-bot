"""
Weekly backtest tracker.

Re-runs the batch backtest over a fixed ticker set, both Alarm D scopes, and
appends the expectancy numbers to data/backtest_history.jsonl. Over time this
shows whether the measured edge is stable, improving, or decaying as new market
data rolls in — WITHOUT changing any rule. It just measures.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tiger import batch

ET = ZoneInfo("America/New_York")
HISTORY_PATH = Path(__file__).parents[2] / "data" / "backtest_history.jsonl"

TICKERS = ["NVDA", "AMD", "AVGO", "TSLA", "META", "AAPL", "MSFT",
           "GOOGL", "AMZN", "NFLX", "COIN", "MU", "PLTR", "HOOD", "SMCI"]


def run_weekly() -> dict:
    now = datetime.now(ET)
    result = {"date": now.date().isoformat(), "recorded_at": now.isoformat(), "scopes": {}}

    # A/B the two exit modes — this is the meaningful comparison now that the
    # evidence-based "run" variant exists. Keyed "alarms" / "run".
    for mode in ("alarms", "run"):
        try:
            br = batch.run_batch(TICKERS, exit_mode=mode)
            agg = batch.aggregate(br.sessions)
            result["scopes"][mode] = {
                "trades": agg["trades"],
                "win_rate": round(agg["win_rate"], 1),
                "total_pnl": round(agg["total_pnl"], 2),
                "expectancy": round(agg["expectancy"], 2),
                "profit_factor": round(agg["profit_factor"], 2),
            }
        except Exception as exc:
            result["scopes"][mode] = {"error": str(exc)}

    HISTORY_PATH.parent.mkdir(exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(result) + "\n")
    return result


if __name__ == "__main__":
    r = run_weekly()
    print(f"Weekly backtest {r['date']}:")
    for scope, s in r["scopes"].items():
        if "error" in s:
            print(f"  {scope}: ERROR {s['error']}")
        else:
            print(f"  {scope:8} | trades {s['trades']:3d} | win {s['win_rate']:4.0f}% | "
                  f"exp ${s['expectancy']:+7.2f}/trade | PF {s['profit_factor']:.2f}")
