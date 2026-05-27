# TIGER SOVEREIGN SYSTEM — COMPLETE BUILD BRIEF

**For:** Claude Code (project context document)
**Source:** Tiger Sovereign Specification v2026.4.29-AA-ULTIMATE
**Purpose:** Build an automated intraday momentum trading bot that executes the Tiger Sovereign strategy on US equities via Alpaca broker API. Paper trading first.

> ⚠️ **NOT the authoritative source.** This is an *expanded brief* written from the author's original PDF — it adds helpful explanation but also introduced interpretations the original contradicts. **`STRATEGY_SPEC_ORIGINAL.md` is authoritative; where they differ, the original wins.** Known conflict: the Alarm D note below (Section 9) defaults to per-Strike `Trade_HVP`, but the **original says session peak (HWM)** — follow the original. See `OPEN_QUESTIONS.md` Q1.
>
> Do not edit the intent of any rule. Ambiguities are tracked in `OPEN_QUESTIONS.md`.

---

## 0. MISSION (READ FIRST)

We are building a **rules-based intraday trading bot** that hunts for opening-range breakouts on pre-market gap stocks, enters with multiple confirmation filters, and exits via six independent "sentinel" alarms.

This is **not** a machine-learning / LLM-driven system. It is a deterministic state machine that executes a human trader's strategy with perfect discipline and machine speed. The edge is in the strategy and the execution quality — not in any AI prediction.

**Stack:**
- **Language:** Python 3.11+
- **Broker:** Alpaca (paper account first, live later)
- **Market data:** Alpaca real-time WebSocket (bars + quotes) + Polygon.io for pre-market scanner
- **Indicators:** pandas-ta or ta-lib
- **Runtime:** Long-running asyncio process on a VPS
- **Logging:** Structured JSON logs + Slack webhook for trade events
- **Persistence:** SQLite (trades, daily P&L, state snapshots)

**Operating constraints:**
- US equities only
- One ticker at a time (for now — expandable to 2-3 in parallel later)
- Paper trading until at least 100+ paper trades show positive expectancy
- $25,000 typical position size, $500 hard stop, $1,500 daily circuit breaker
- Trading hours: 09:30:00 to 16:00:00 ET (entry window 09:36:00 to 15:44:59 ET)

---

## 1. STRATEGY OVERVIEW (PLAIN ENGLISH)

The system trades stocks that have **directional energy** in the morning — meaning a meaningful pre-market gap on news, earnings, or sector momentum. Random sleepy stocks never qualify.

Each morning, a scanner picks the day's best candidate. The bot then:

1. **Records the opening range** — the highest and lowest prices the stock touches between 09:30:00 and 09:35:59 ET. These become levels for the day (ORH = Opening Range High, ORL = Opening Range Low).

2. **Waits for a breakout** — two consecutive 1-minute candle closes above ORH (long setup) or below ORL (short setup).

3. **Verifies the breakout is real** by stacking five independent filters:
   - **Weather:** Is the broader market (QQQ) trending in the same direction?
   - **Pattern:** Did the price actually close beyond the level, twice in a row?
   - **Volume:** Is the breakout backed by real institutional volume?
   - **Trend authority:** Are higher-timeframe momentum indicators strong?
   - **Divergence check:** Is RSI confirming the move (not warning of weakness)?

4. **Sizes the position by conviction** — full size when momentum is dominant, half size when it's strong-but-not-extreme.

5. **Manages the trade with six independent exit alarms** — each detecting a different way the trade could be dying.

6. **Allows up to 3 attempts ("Strikes") per ticker per day** — after Strike 1 exits, the bot can re-enter on continuation breakouts.

7. **Closes everything at 15:49:59 ET** — no overnight risk.

Long entries are called **"Bison"** (charging up). Short entries are called **"Wounded Buffalo"** (falling down). These are just the strategy author's naming convention — they refer to direction.

---

## 2. GLOSSARY (DEFINE EVERY TERM)

| Term | Meaning |
|---|---|
| **Ticker** | The stock symbol being traded (e.g., NVDA, TSLA) |
| **1m / 5m bar** | A candlestick representing 1 minute or 5 minutes of price action (open, high, low, close, volume) |
| **ORH** | Opening Range High — the highest price the stock hit between 09:30:00 and 09:35:59 ET. **Locked permanently at 09:35:59.** |
| **ORL** | Opening Range Low — the lowest price in the same window. Locked the same way. |
| **NHOD** | New High of Day — the highest price reached so far today. Updates in real time. |
| **NLOD** | New Low of Day — the lowest price reached so far today. Updates in real time. |
| **HWM / HVP** | High Water Mark / High Value Point — the peak value reached during the session. Used for "exhaustion" detection. |
| **Trade_HVP** | Per-strike peak of 5-minute ADX. Resets to zero at the start of each new Strike. |
| **Stored_Peak_Price** | Memory variable. Updated at the exact tick a new NHOD or NLOD is set. Used for Alarm E (divergence detection). |
| **Stored_Peak_RSI** | Memory variable. The RSI(15) value at the exact moment Stored_Peak_Price was set. |
| **Strike** | One complete trade lifecycle from entry to exit. Max 3 Strikes per ticker per day. |
| **Bison** | A long position (betting price goes up). |
| **Buffalo / Wounded Buffalo** | A short position (betting price goes down). |
| **VWAP** | Volume-Weighted Average Price. The average price of trades weighted by volume. Anchored to 09:30 AM ET means VWAP starts fresh at market open. |
| **9-EMA** | 9-period Exponential Moving Average — a fast-reacting moving average that weights recent bars more heavily. Computed on the 5-minute timeframe in this strategy. |
| **RSI(15)** | 15-period Relative Strength Index. Oscillates 0-100. Measures momentum strength. |
| **ADX** | Average Directional Index. Measures **trend strength** (not direction). 0-100. Above 25 = strong trend, below 20 = weak/no trend. |
| **DI+** | Positive Directional Indicator. The "upward pressure" component of ADX. High DI+ means buyers are dominant. |
| **DI-** | Negative Directional Indicator. The "downward pressure" component. High DI- means sellers are dominant. |
| **STOP MARKET** | An order that becomes a market order (executes at next available price) once a trigger price is hit. Used for stop-losses. |
| **LIMIT order** | An order to buy/sell at a specified price or better. Can sit unfilled if price never reaches it. |
| **MARKET order** | An order that executes immediately at the best available price. |
| **Slippage** | The difference between expected fill price and actual fill price. |
| **PDT** | Pattern Day Trader rule — US regulation requiring $25k+ account for >3 day trades/week in a margin account. |

---

## 3. DATA & INDICATORS REQUIRED

Every minute, the bot must have access to (per ticker):

### Price/volume data
- 1-minute OHLCV bars (real-time, streamed)
- 5-minute OHLCV bars (built from 1m or streamed directly)
- Current bid, ask, last trade price

### Calculated indicators (1-minute timeframe)
- RSI with period 15
- ADX with period 14 (standard)
- DI+ with period 14
- DI- with period 14
- Rolling 55-bar volume average (sum of last 55 1m volumes / 55)

### Calculated indicators (5-minute timeframe)
- ADX with period 14
- DI+ with period 14
- DI- with period 14
- 9-period EMA of close
- Session VWAP anchored to 09:30 ET

### QQQ-specific (for "weather" filter)
- QQQ 5-minute close
- QQQ 5-minute 9-EMA
- QQQ session VWAP anchored to 09:30 ET

### Per-session state
- ORH (locked at 09:35:59)
- ORL (locked at 09:35:59)
- Current NHOD (updates each tick)
- Current NLOD (updates each tick)
- Stored_Peak_Price (updates on each new NHOD or NLOD)
- Stored_Peak_RSI (updates on each new NHOD or NLOD)
- Session peak 5m ADX (HWM)
- Trade_HVP (per-active-strike peak 5m ADX, resets each Strike)
- Strike counter (0, 1, 2, or 3)
- Current position size and direction
- Session realized P&L

**Implementation note:** Build a `MarketState` object that holds all of this. Update it on every new 1m bar close. Persist snapshots to SQLite every minute for crash recovery.

---

## 4. TIME WINDOWS (CRITICAL — DO NOT MISS)

All times in **US Eastern Time (ET)**. Handle DST transitions correctly.

| Time | Event |
|---|---|
| 08:00:00 ET | Pre-market scanner runs, picks ticker for the day |
| 09:30:00 ET | Market opens. Begin recording bars. Begin VWAP anchoring. |
| 09:30:00 – 09:35:59 ET | Opening Range formation window. Track running high/low. |
| **09:35:59 ET** | **ORH and ORL LOCK PERMANENTLY for the rest of the day.** |
| 09:36:00 ET | **Entry window opens.** Bot can take Strike 1, 2, or 3 from here. |
| 10:00:00 ET | Volume Gate becomes mandatory (before this, volume filter is skipped — first 30 min always has high volume baseline) |
| 15:44:59 ET | **Entry window closes.** No new positions after this. |
| 15:49:59 ET | **EOD Flush.** Force MARKET exit on any open position. Cancel all working orders. |
| 16:00:00 ET | Market close |

---

## 5. THE STRIKE SEQUENCE (CORE LOOP)

A "Strike" is one complete trade lifecycle (entry → exit). The bot is allowed up to **3 Strikes per ticker per day**. A new Strike can only begin when `Position == 0` (no open position from a prior Strike).

| Strike # | Permission Condition (Long) | Permission Condition (Short) | Target Level |
|---|---|---|---|
| 1 | 2 consecutive 1m closes above **ORH** | 2 consecutive 1m closes below **ORL** | Fixed at 09:35:59 |
| 2 | 2 consecutive 1m closes above **NHOD** | 2 consecutive 1m closes below **NLOD** | Dynamic (current extreme) |
| 3 | 2 consecutive 1m closes above **NHOD** | 2 consecutive 1m closes below **NLOD** | Dynamic (current extreme) |

**Why this matters:** Strike 1 trades the static opening range — the most reliable level of the day. Strikes 2 and 3 chase continuation moves — the stock has already broken out and is making new highs/lows, and we're betting on continuation.

**Strike counter resets** at the start of each new trading day (08:00 ET).

**State transitions:**
- After Strike 1 fills → Strike counter = 1, position state = OPEN
- After Strike 1 exits → position state = FLAT, Strike counter remains at 1
- After Strike 2 fills → counter = 2, etc.
- After 3 Strikes complete OR position open at 15:49:59 → no new Strikes today

---

## 6. ALARM E: THE DIVERGENCE TRAP (DEEP DIVE)

This is the **smartest mechanic** in the entire strategy. Understand it deeply.

### What divergence means

When a stock makes a new high but RSI **doesn't make a new high**, that's "bearish divergence" — the price is going up but the momentum behind the move is weakening. It usually means the trend is about to reverse.

Same in reverse: when a stock makes a new low but RSI is **higher** than at the previous low, that's "bullish divergence" — selling pressure is exhausting.

### How the system tracks it

Every time a new NHOD or NLOD is set (the exact tick, not the next bar), record:
- `Stored_Peak_Price = current price`
- `Stored_Peak_RSI = current RSI(15)`

Then on the next NHOD/NLOD update, check:

**For longs (Bison divergence):**
```
divergence = (current_price > Stored_Peak_Price) AND (current_RSI < Stored_Peak_RSI)
```
A new price high made on weaker momentum.

**For shorts (Buffalo divergence):**
```
divergence = (current_price < Stored_Peak_Price) AND (current_RSI > Stored_Peak_RSI)
```
A new price low made on stronger (less negative) momentum.

### Alarm E acts in two modes

**MODE 1 — Pre-Entry Filter (binary):**
If divergence is currently TRUE, the bot is **prohibited** from opening new Strike 2 or Strike 3 positions. (Strike 1 is exempt because divergence can't really exist until NHOD/NLOD has updated past the opening range.)

**MODE 2 — Post-Entry Sentinel (aggressive):**
If divergence becomes TRUE *while a position is open*, immediately ratchet the STOP MARKET to **Current Price ± 0.25%**:
- Long position: new stop = `current_price × 0.9975`
- Short position: new stop = `current_price × 1.0025`

This tightens the stop dramatically the instant the move shows hidden weakness — capturing most of the gains before the reversal hits.

### Implementation notes
- Update `Stored_Peak_*` on the **tick** a new extreme is set, not on bar close
- For "current price > Stored_Peak_Price" — use strict `>`, not `>=`
- After the stop is ratcheted by Alarm E, the new stop should only move favorably (a "ratchet" — never moves against the trade). If a subsequent Alarm E fires deeper into the trade, ratchet again.

---

## 7. BISON (LONG) ENTRY — FULL LOGIC

Execute this check on every 1-minute bar close, in order. If any phase fails, abort and wait for the next bar.

### Phase 1: Weather Check (market environment)
```
QQQ_5m_close > QQQ_5m_9EMA
  AND
QQQ_current_price > QQQ_session_VWAP_from_0930
```
**Why:** Don't take longs when the broader market is selling off. QQQ proxies Nasdaq sentiment, which dominates intraday flow for most momentum stocks.

### Phase 2: Permit (breakout confirmation)
```
Strike 1: last_two_1m_closes both > ORH
Strike 2 or 3: last_two_1m_closes both > NHOD
```
**Why:** A single bar can spike above a level on noise. Two consecutive closes above means real commitment.

### Phase 2.5: Volume Gate (only after 10:00 AM)
```
current_1m_volume >= rolling_55_bar_volume_average × 1.0
```
**Why:** A breakout without volume is retail noise. Demand institutional participation. Skipped before 10:00 ET because opening volume is inherently elevated.

### Phase 3: Authority + Momentum (trend strength check)
```
5m DI+ > 25                  # Higher-timeframe authority
  AND
5m ADX > 20                  # Trend exists at all
  AND
Alarm E (divergence) == False  # No hidden weakness
```
**Why:** ADX confirms a trend is present. DI+ confirms it's an upward trend with strength. Alarm E confirms momentum isn't already fading.

### Phase 3.5: Sizing Decision
```
IF 1m DI+ > 30
    size = 100% (Full Strike)
ELIF 1m DI+ between 25 and 30:
    size = 50% (Scaled Strike — half now, half later)
ELSE:
    do not enter
```
**Why:** When near-term (1m) momentum is dominant (DI+ > 30), commit full size. When it's strong but not extreme (25-30), enter half and add only if it strengthens.

### Phase 4: Order Placement
```
LIMIT BUY at (current_ask × 1.001)
```
**Why:** Paying 0.1% above the ask ensures the order fills immediately in a fast-moving breakout. Pure market orders can slip badly in momentum stocks. The LIMIT acts as a marketable order with a slippage cap.

### Phase 5: Scale-In (only for Scaled Strikes)
If first 50% filled, monitor for:
```
1m DI+ > 30
  AND
new NHOD set
  AND
Alarm E == False
```
If all three are true → submit additional 50% LIMIT at ask × 1.001.

---

## 8. WOUNDED BUFFALO (SHORT) ENTRY — FULL LOGIC

Mirror image of Bison. Same structure, inverted conditions.

### Phase 1: Weather Check
```
QQQ_5m_close < QQQ_5m_9EMA
  AND
QQQ_current_price < QQQ_session_VWAP_from_0930
```

### Phase 2: Permit
```
Strike 1: last_two_1m_closes both < ORL
Strike 2 or 3: last_two_1m_closes both < NLOD
```

### Phase 2.5: Volume Gate (only after 10:00 AM)
Same as Bison: `current_1m_volume >= 55_bar_volume_avg × 1.0`

### Phase 3: Authority + Momentum
```
5m DI- > 25
  AND
5m ADX > 20
  AND
Alarm E (Buffalo divergence) == False
```

### Phase 3.5: Sizing
```
IF 1m DI- > 30:
    size = 100% (Full Strike)
ELIF 1m DI- between 25 and 30:
    size = 50% (Scaled Strike)
```

### Phase 4: Order Placement
```
LIMIT SELL_SHORT at (current_bid × 0.999)
```

### Phase 5: Scale-In
```
1m DI- > 30
  AND
new NLOD set
  AND
Alarm E == False
→ Add additional 50%
```

**Note on shorting:** Alpaca requires HTB (hard-to-borrow) checks. Some tickers can't be shorted on any given day. The bot must check shortability before placing the order — if not shortable, skip the trade and log it.

---

## 9. THE SENTINELS — EXIT ALARMS A THROUGH E

Once in a position, **all five alarms** run continuously alongside the hard stop. Any one triggering causes either a market exit or a stop ratchet. They are independent — multiple can fire on the same trade.

| Alarm | Trigger | Action |
|---|---|---|
| **A — Flash Move** | 1-minute price move > 1% against position | MARKET EXIT |
| **B — Trend Death** | 5-minute candle closes across (against) the 5m 9-EMA | MARKET EXIT |
| **C — Tiger Grip** | 3 consecutive 1-minute ADX values declining | RATCHET STOP to current price ± 0.25% |
| **D — HVP Lock** | 5m ADX drops below 75% of session peak (HWM) | MARKET EXIT |
| **E — Divergence** | (see Section 6) New extreme on lower-momentum RSI | RATCHET STOP to current price ± 0.25% |

### Detailed alarm explanations

**Alarm A — Flash Move (panic exit):**
If the price moves more than 1% against the position in a single minute, something is wrong — news, a halt-pending event, or a sudden reversal. Don't wait for the hard stop; exit at market now. For a long, this means current price < entry × 0.99 within any 1-minute bar. For a short, current price > entry × 1.01.

**Alarm B — Trend Death:**
The 5m 9-EMA is the trend's "spine." When a full 5-minute bar closes on the wrong side of it, the trend is structurally broken. For a long, this means a 5m candle closes below the 5m 9-EMA. For a short, a 5m candle closes above.

**Alarm C — Tiger Grip:**
ADX measures trend strength. When ADX declines for 3 consecutive 1-minute bars, the trend is losing steam — not dead yet, but weakening. Don't exit fully, but tighten the stop dramatically (±0.25% from current price) to lock in gains in case momentum dies completely.

**Alarm D — HVP Lock (exhaustion exit):**
"HVP" = High Value Point = the session peak of 5m ADX. If current 5m ADX drops below 75% of that peak, the trend has lost a quarter of its strength from peak — historically the point of no return. Exit at market.

*Note: The spec is slightly ambiguous about whether HWM refers to session-wide peak or per-strike Trade_HVP. Default to using `Trade_HVP` (per-strike peak) since the glossary defines it as "peak 5m ADX during an active Strike." Confirm with strategy author.*

**Alarm E — Divergence:**
See Section 6 for full logic. Ratchets stop to ±0.25%.

### Ratchet mechanics
"Ratchet" means the stop only moves favorably (tighter, never looser):
- For a long: new_stop = MAX(existing_stop, current_price × 0.9975)
- For a short: new_stop = MIN(existing_stop, current_price × 1.0025)

If a later Alarm C or E fires deeper into profit, the stop ratchets tighter again. Never relaxes.

---

## 10. RISK MANAGEMENT (HARD LIMITS)

### Hard Stop (per trade)
Immediately upon entry fill, place a resting **STOP MARKET** order at the price level that corresponds to a **$500 loss** on the position.

Math:
```
For a long at fill_price with N shares:
    stop_price = fill_price - (500 / N)

For a short at fill_price with N shares:
    stop_price = fill_price + (500 / N)
```

This stop sits at the broker even if the bot crashes. It is the absolute backstop.

### Daily Circuit Breaker
If cumulative session realized P&L hits **-$1,500** at any point:
- Halt all new entries (no Strike 2, no Strike 3, no other tickers)
- Allow open positions to manage through their sentinels (don't force-exit profitable trades)
- Once those exit, bot goes flat and stays flat until next trading day

### EOD Flush
At **15:49:59 ET** sharp:
- Cancel all working orders (limits, stops)
- Submit MARKET orders to flatten any open position
- Log the flush event
- Bot enters end-of-day idle state

### Entry Window
- No new entries before 09:36:00 ET
- No new entries after 15:44:59 ET (gives 5 minutes of buffer before EOD flush)

---

## 11. ORDER EXECUTION DETAILS

### Order types used
| Order Type | When Used |
|---|---|
| LIMIT (entry) | All entries. Buy at ask × 1.001, sell short at bid × 0.999 |
| STOP MARKET | Hard stop at $500 loss level, plus ratcheted stops from alarms |
| MARKET | All sentinel-triggered exits (A, B, D) and EOD flush |

### Order lifecycle (single Strike)
1. Phase checks pass → submit LIMIT entry order
2. Wait up to 30 seconds for fill. If unfilled, cancel.
3. On fill confirmation → immediately submit resting STOP MARKET at -$500 level
4. Begin running alarms each minute
5. On exit (alarm fires, stop hits, or scale-in adds) → update state
6. After exit fill → cancel any remaining stops, increment Strike counter

### Critical implementation detail: order/state synchronization
- Subscribe to Alpaca trade_updates WebSocket
- Never assume an order filled — wait for the `fill` event
- If the bot restarts mid-trade, reconcile state from Alpaca's position endpoint, not from local state

---

## 12. PRE-MARKET SCANNER (RUNS DAILY AT 08:00 ET)

The scanner picks one ticker to trade each day. Logic:

1. Query Polygon.io for all US equities with:
   - Pre-market gap (current vs prior close) ≥ 3% (absolute value)
   - Pre-market cumulative volume ≥ 500,000 shares
   - Price between $10 and $300
   - Float between 20M and 500M shares
   - 30-day average daily volume ≥ 5,000,000 shares

2. Rank surviving candidates by score:
   ```
   score = abs(gap_percent) × log(premarket_volume)
   ```

3. Pick the **#1 ranked ticker** for the day. Persist to SQLite.

4. If no ticker qualifies → bot logs "no setup today" and stays idle.

**Filter rationale:**
- Gap ≥ 3%: needs energy
- Pre-market volume ≥ 500k: confirms market interest, not just a single big print
- Price band: avoid penny stocks (unreliable) and ultra-high prices (capital efficiency)
- Float band: avoid micro-floats (whippy, easy to manipulate) and mega-floats (won't move enough)
- Avg daily volume: liquidity for clean fills

---

## 13. STATE MACHINE (CORE OBJECTS TO BUILD)

Suggested Python class structure:

```python
# Per-session state
class MarketState:
    ticker: str
    orh: float | None         # locked at 09:35:59
    orl: float | None         # locked at 09:35:59
    nhod: float
    nlod: float
    stored_peak_price: float | None
    stored_peak_rsi: float | None
    session_peak_5m_adx: float  # HWM
    session_realized_pnl: float
    strikes_taken: int  # 0-3
    halt_circuit_breaker: bool

# Per-strike state
class StrikeState:
    strike_number: int
    direction: Literal["long", "short"]
    entry_price: float
    fill_size: int
    is_scaled: bool       # True if entered at 50%
    is_full_filled: bool  # True once scale-in completes
    hard_stop_order_id: str
    trade_hvp_5m_adx: float  # peak 5m ADX during this strike
    entry_time: datetime
    exit_price: float | None
    exit_time: datetime | None
    exit_reason: str | None  # 'hard_stop' | 'alarm_a' | ... | 'eod_flush'

# Indicators cache (updated on each new bar)
class IndicatorSnapshot:
    timestamp: datetime
    rsi_15_1m: float
    adx_14_1m: float
    di_plus_1m: float
    di_minus_1m: float
    rolling_volume_55_1m: float
    adx_14_5m: float
    di_plus_5m: float
    di_minus_5m: float
    ema_9_5m: float
    vwap_5m: float
    qqq_5m_close: float
    qqq_ema_9_5m: float
    qqq_vwap_5m: float
```

---

## 14. SUGGESTED BUILD ORDER

Build and test each module before moving to the next.

1. **`indicators.py`** — RSI, ADX, DI+/-, EMA, VWAP, rolling volume. Verify against TradingView on a sample dataset.
2. **`bars.py`** — 1m and 5m bar aggregation from Alpaca WebSocket trades.
3. **`state.py`** — `MarketState` and `StrikeState` classes with persistence to SQLite.
4. **`alarms.py`** — Each alarm A-E as a pure function `(state, indicators) -> AlarmResult`.
5. **`entry.py`** — Bison and Buffalo entry phase checks.
6. **`broker.py`** — Alpaca order placement wrapper (LIMIT, STOP MARKET, MARKET). Mock first.
7. **`risk.py`** — Hard stop sizing, circuit breaker, EOD flush.
8. **`scanner.py`** — Daily pre-market scanner via Polygon.io.
9. **`main.py`** — Async event loop: WebSocket → bar close → state update → entry check → alarm check → orders.
10. **`logging_setup.py`** — Structured JSON logs + Slack webhook for trade events.
11. **`backtest_harness.py`** *(optional but recommended)* — Replay historical bars through the same logic to validate before paper trading.

> **NOTE (deviation agreed with project owner):** We are promoting the backtest harness to **Phase 1, mandatory and first**. The strategy will be proven on free historical data before any live engine or paid data subscription is built. See `../ROADMAP.md`.

---

## 15. QUESTIONS FOR THE STRATEGY AUTHOR

These details aren't fully specified in the original document — confirm before going live. Tracked and updated in `OPEN_QUESTIONS.md`.

1. **Alarm D scope:** Does HWM/HVP refer to session-wide peak 5m ADX or to per-Strike `Trade_HVP`? (Default assumption: per-Strike.)
2. **Ratchet stop interaction:** When Alarm C or E fires and ratchets the stop, does that replace the existing hard $500 stop or sit alongside it? (Default: replace with the tighter of the two — i.e., the more protective stop wins.)
3. **Volume Gate strictness:** Spec says "Volume >= 100% of 55-bar avg." Strict `>=` or just `>`? (Default: strict `>=`.)
4. **Scale-in stop:** When the second 50% fills on a Scaled Strike, does the $500 hard stop adjust to reflect the new full position size? (Default: yes — recalculate based on total filled size and weighted entry price.)
5. **Same-day re-entry direction:** Can Strike 2 be a *Buffalo* if Strike 1 was a *Bison*? (i.e., can the bot flip direction within the same ticker's 3 Strikes?) Spec is silent. (Default: yes, if conditions trigger.)
6. **Bar timezone source:** Confirm Alpaca returns bar timestamps in UTC and the bot converts to ET internally.
7. **Halt handling:** What if the stock is halted (LULD circuit breaker)? Spec doesn't address. (Suggested default: cancel all working orders, hold position, wait for halt to resolve, then resume normal alarm processing.)

---

## 16. FINAL NOTES FOR CLAUDE CODE

- **Build incrementally.** Each module should be unit-tested before integration.
- **Mock everything broker-side first.** Don't connect to live Alpaca paper API until the full logic flow is verified against synthetic data.
- **Log obsessively.** Every state transition, every indicator value at decision time, every order event. When something goes wrong on day 47 of paper trading, you'll need this.
- **Persist state every minute.** SQLite snapshot on each 1m bar close. Crash recovery is non-negotiable.
- **Slack alerts for:** every entry, every exit (with P&L), every alarm trigger, every circuit-breaker event, daily summary at 16:05 ET.
- **Time handling:** Use `pendulum` or `pytz` correctly. Eastern Time, DST-aware. Never use naive datetimes.
- **Floating point:** Use `decimal.Decimal` for all price/P&L math. Floating-point math will eventually cost you a trade.

---

**End of build brief.**
