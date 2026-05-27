"""Indicator validation report — Rung 2 of the trust ladder.

Produces a human-readable report of our computed indicator values for a real
stock at real timestamps, so the strategy author can confirm they match their
TradingView charts. If these match, the whole engine's foundation is sound; if
not, the indicator math gets fixed before anything else is trusted.

Compute is pure (testable offline); formatting is separate. The CLI writes a
markdown file you can hand to the author:

    uv run python -m tiger.validate NVDA
"""

from __future__ import annotations

import pandas as pd

from tiger import indicators
from tiger.backtest import _resample_5m


def compute_validation(stock_1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (df_1m, df_5m) with OHLCV + all indicators, computed over the full
    input (warmup included so values are warm). Slice to the day of interest later.
    """
    high, low, close, vol = (stock_1m["high"], stock_1m["low"],
                             stock_1m["close"], stock_1m["volume"])

    df1 = stock_1m[["open", "high", "low", "close", "volume"]].copy()
    df1["RSI(15)"] = indicators.rsi(close, 15)
    dmi1 = indicators.adx_di(high, low, close, 14)
    df1["ADX(14)"] = dmi1["adx"]
    df1["DI+(14)"] = dmi1["di_plus"]
    df1["DI-(14)"] = dmi1["di_minus"]

    s5 = _resample_5m(stock_1m)
    df5 = s5[["open", "high", "low", "close", "volume"]].copy()
    dmi5 = indicators.adx_di(s5["high"], s5["low"], s5["close"], 14)
    df5["ADX(14)"] = dmi5["adx"]
    df5["DI+(14)"] = dmi5["di_plus"]
    df5["DI-(14)"] = dmi5["di_minus"]
    df5["EMA(9)"] = indicators.ema(s5["close"], 9)
    df5["VWAP"] = indicators.session_vwap(s5["high"], s5["low"], s5["close"], s5["volume"])
    return df1, df5


def _fmt(df: pd.DataFrame) -> str:
    out = df.copy()
    out.index = [ts.strftime("%H:%M") for ts in out.index]
    price_cols = [c for c in out.columns if c in ("open", "high", "low", "close",
                                                  "EMA(9)", "VWAP")]
    ind_cols = [c for c in out.columns if c in ("RSI(15)", "ADX(14)", "DI+(14)", "DI-(14)")]
    for c in price_cols:
        out[c] = out[c].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—")
    for c in ind_cols:
        out[c] = out[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
    if "volume" in out.columns:
        out["volume"] = out["volume"].map(lambda v: f"{int(v):,}" if pd.notna(v) else "—")
    return out.to_string()


def build_report(ticker: str, df_1m: pd.DataFrame, df_5m: pd.DataFrame,
                 target=None) -> str:
    """Build the markdown validation report for the target day."""
    dates = pd.DatetimeIndex(df_1m.index.normalize().unique())
    target = dates[-1] if target is None else pd.Timestamp(target)
    day1 = df_1m[df_1m.index.normalize() == target]
    day5 = df_5m[df_5m.index.normalize() == target]

    win1 = day1.between_time("10:00", "10:20")    # 21 contiguous 1m bars (warm)
    win5 = day5.between_time("09:30", "11:30")     # ~24 5m bars from the open

    date_str = str(target.date())
    return f"""# Indicator Validation — {ticker}, {date_str}

**Purpose:** confirm our computed indicators match your TradingView charts.
If these line up, the engine's foundation is correct. If a column is off, tell
us which one and we fix the math before trusting any backtest result.

## How to set up TradingView to match

Open **{ticker}**, **{date_str}**, **regular session (09:30–16:00 ET)**.

- **1-minute chart** — add:
  - **RSI**, length **15**, source **close**
  - **Directional Movement Index (DMI)** — ADX Smoothing **14**, DI Length **14** (read ADX, DI+, DI−)
- **5-minute chart** — add:
  - **DMI** — ADX Smoothing **14**, DI Length **14**
  - **EMA**, length **9**, source **close**
  - **VWAP**, anchored to the **session** (resets at 09:30)

⚠️ **Read this first — why some columns may differ legitimately:**
Our free data feed (yfinance) and TradingView's feed are not identical. **Check
the OHLC prices first** — if a bar's open/high/low/close already differ, the
indicators *should* differ too (different inputs → different outputs); that's a
data-source gap, not a math bug. The columns to trust most are the **price-only
indicators (RSI, ADX, DI+, DI−, EMA)** when the OHLC matches. **VWAP and volume
will likely differ** because consolidated volume varies by feed — don't sweat VWAP.

---

## 1-minute indicators — {ticker} {date_str}, 10:00–10:20 ET

```
{_fmt(win1)}
```

## 5-minute indicators — {ticker} {date_str}, 09:30–11:30 ET

```
{_fmt(win5)}
```

---

**What to report back:** for each indicator, does it match TradingView (within
rounding) on the bars where the OHLC also matches? A simple "RSI ✓, ADX ✓, DI ✓,
EMA ✓, VWAP off (expected)" is perfect. Anything that's *off despite matching
OHLC* is a real finding — tell us the column and we'll fix it.
"""


def main():  # pragma: no cover - manual entrypoint
    import sys
    from pathlib import Path

    from tiger import data

    ticker = (sys.argv[1] if len(sys.argv) > 1 else "NVDA").upper()
    stock = data.load_yfinance(ticker)
    df1, df5 = compute_validation(stock)
    report = build_report(ticker, df1, df5)

    out = Path(__file__).resolve().parents[2] / "docs" / "INDICATOR_VALIDATION.md"
    out.write_text(report)
    print(report)
    print(f"\n[written to {out}]")


if __name__ == "__main__":
    main()
