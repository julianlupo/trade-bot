# Tiger Sovereign — Build Roadmap

The single source of truth for *where we are*. Update the status boxes as we go. Phases are gated: we do not start a phase until the prior one is signed off.

**Guiding decision:** Backtest first. Prove the strategy on free historical data before building the live engine or paying for market data. Money is only spent entering Phase 2.

---

## Phase 1 — Prove the edge ($0 spent)

Goal: run the full strategy logic over a year of historical 1-minute bars and look at whether it actually makes money. Reuses ~70% of the code the live bot needs.

| # | Module | What it does | Status |
|---|--------|--------------|--------|
| 1 | `indicators.py` | RSI(15), ADX/DI±(14), 9-EMA, VWAP, rolling 55-bar volume. Must match TradingView. | ✅ built + 13 unit tests pass. Final TradingView cross-check pending real data. |
| 2 | `state.py` | `MarketState` + `StrikeState` (Decimal money). | ✅ built |
| 3 | `alarms.py` | Sentinels A–E as pure functions + divergence helper. | ✅ built + tested |
| 4 | `entry.py` | Bison (long) + Buffalo (short) entry phase checks + scale-in (v2). | ✅ built + tested (full + scaled sizing, scale-in add) |
| 5 | `risk.py` | Hard-stop sizing, ratchet math, circuit breaker, entry slippage. | ✅ built + tested |
| 6 | `backtest.py` | Bar-replay engine: indicators→state→entry→alarms→stop→exit. Trade log + report. | ✅ built; runs on synthetic day, 28 tests green |
| 7 | Data loader | `data.py`: synthetic session (offline) ✅ + yfinance real 1m (last ~7d) ✅. Alpaca/Polygon = Phase 2. | ✅ built |
| — | **GATE** | Review expectancy with Julian + strategy author. **Go / no-go on Phase 2.** | ☐ |

**Open items to revisit before the gate:**
- ✅ Scale-in + half-size sizing now implemented (v2). Re-run after: still net negative on the tiny sample (exp ≈ −$60–62/trade).
- Backtest fills are bar-close approximations (no live bid/ask, no gap slippage on stops).
- **Finding:** Alarm D uses the SESSION peak 5m ADX (per the original spec). The overnight gap can inflate the opening 5m ADX, making Alarm D fire early. Real-data behavior TBD — relates to OPEN_QUESTIONS.md Q1 (worth raising with the author).
- Indicator values not yet cross-checked against the author's TradingView charts (needs real data + author).

## Phase 2 — Live on paper (costs ~$99–300/mo in data)

Only if Phase 1 shows positive expectancy.

| # | Module | What it does | Status |
|---|--------|--------------|--------|
| 8 | `bars.py` | Build live 1m/5m bars from Alpaca trade WebSocket. | ☐ |
| 9 | `broker.py` | Alpaca order wrapper (LIMIT / STOP MARKET / MARKET) + order/state reconciliation. | ☐ |
| 10 | `scanner.py` | 08:00 ET pre-market gap scanner (needs Polygon). | ☐ |
| 11 | `main.py` | Async event loop tying it all together. | ☐ |
| 12 | `logging_setup.py` | JSON logs + Slack trade alerts + daily summary. | ☐ |
| 13 | Deploy | Long-running process on a VPS/Railway, DST-aware scheduling. | ☐ |
| — | **GATE** | 100+ paper trades logged with positive expectancy. | ☐ |

## Phase 3 — Real money

Only after Phase 2's gate. Flip Alpaca keys from paper to live, start with minimum size, watch closely.

| # | Step | Status |
|---|------|--------|
| 14 | Strategy author signs off on all `OPEN_QUESTIONS.md` answers. | ☐ |
| 15 | Confirm account ≥ $25k (PDT rule) + risk limits wired correctly. | ☐ |
| 16 | Go live, small size, daily review. | ☐ |

---

## Decisions log

- **2026-05-26** — Project created. Backtest-first agreed. Python 3.11 + uv. Indicators: pandas-ta to start, hand-roll Wilder's if TradingView numbers don't match. Alpaca account exists (paper); no Polygon yet (not needed until Phase 2).
- **2026-05-26** — Decided to hand-roll all indicators (Wilder's, pandas/numpy only) — pandas-ta fought our numpy version + doesn't match TradingView. `indicators.py` built, 13 tests pass.
- **2026-05-26** — Obtained the **original author PDF** (`docs/STRATEGY_SPEC_ORIGINAL.md`, now authoritative). It settles Q3 (`>=`, confirmed) and **Q1 (Alarm D = SESSION peak, NOT per-Strike — overrode the earlier proxy guess)**. Q2/4/5/6/7 still not addressed in the original; defaults stand. New sub-Q: `Trade_HVP` is defined but unused in the original — ask author.
- **2026-05-27** — Built `batch.py` + dashboard batch tab + Alarm D scope toggle. **First real-data expectancy read (8 tickers × ~5 days, tiny sample): the strategy LOSES money** — expectancy ≈ −$63 to −$66/trade, win rate 14–21%, profit factor 0.12–0.18, under BOTH Q1 readings. Per-Strike Alarm D removes pathological 2-min exits (good evidence for author) but doesn't fix profitability; losses dominated by ratchet-stop whipsaws. **NOT a verdict** — sample is tiny + indicators not yet TradingView-validated. Do NOT tune to fit this sample. Real next steps: validate indicators vs TradingView, get author answers, get deeper data (Phase 2).
