# TIGER SOVEREIGN SYSTEM — ORIGINAL SOURCE

**This is the authoritative strategy document**, transcribed verbatim from the strategy author's PDF (`Complete Technical Specification | v2026.4.29-AA-ULTIMATE`).

> Where `STRATEGY_SPEC.md` (the expanded brief) and this original disagree, **this original wins.** The expanded brief added helpful explanation but also introduced at least one interpretation that contradicts the source (see `OPEN_QUESTIONS.md`, Q1).

**Architectural Note:** This version prioritizes institutional momentum alignment. Alarm E acts as both a binary filter and an aggressive sentinel.

---

## SECTION 0: GLOSSARY OF TERMS

- **ORH / ORL:** Opening Range High / Low (fixed at 09:35:59).
- **NHOD / NLOD:** New High / Low of Day (dynamic, updates in real time).
- **HWM / HVP:** High Water Mark / High Value Point (peak session indicator).
- **Trade_HVP:** Variable tracking peak 5m ADX during an active Strike; resets each Strike.
- **Stored_Peak_Price / Stored_Peak_RSI:** Memory variables for Alarm E tracking.

---

## SECTION 1: SYSTEM CONCEPTS & ALARM E

### 1. THE STRIKE SEQUENCE

A Strike represents a complete trade lifecycle (Entry to Exit). Max 3 Strikes per ticker per day. Subsequent strikes require Position = 0.

| Strike | Permission Condition | Target Level |
|---|---|---|
| 1 | 2x 1m close above/below ORH/ORL | Fixed (Set at 09:35:59) |
| 2 | 2x 1m close above/below NHOD/NLOD | Dynamic (Current Extreme) |
| 3 | 2x 1m close above/below NHOD/NLOD | Dynamic (Current Extreme) |

### 2. ALARM E: THE DIVERGENCE TRAP

The bot monitors the relationship between Price and RSI(15) at every New High of Day (NHOD) or New Low of Day (NLOD).

- **Variable Tracking:** Store `Stored_Peak_Price` and `Stored_Peak_RSI` at the exact tick of every new extreme.
- **Divergence Trigger (Bison):** (Current Price > Stored_Peak_Price) AND (Current RSI < Stored_Peak_RSI).
- **Divergence Trigger (Buffalo):** (Current Price < Stored_Peak_Price) AND (Current RSI > Stored_Peak_RSI).
- **PRE-ENTRY FILTER:** If Divergence = TRUE, the bot is prohibited from opening new Strike 2 or Strike 3 positions.
- **POST-ENTRY SENTINEL:** If Divergence = TRUE while a position is open, immediately ratchet STOP MARKET to Current Price ± 0.25%.

---

## SECTION 2: THE BISON (LONG)

### PHASE 1 & 2: WEATHER & PERMITS
- **Weather:** QQQ(5m) > 9-EMA AND QQQ > 9:30 AM Anchor VWAP.
- **Permit:** Two consecutive 1m closes above Target Level (ORH for Strike 1 | NHOD for Strikes 2/3).
- **Volume Gate:** 1m Volume >= 100% of 55-bar rolling average (Required after 10:00 AM).

### PHASE 3: SIZING & EXECUTION
**Authority:** 5m DI+ > 25. **Momentum:** 5m ADX > 20 AND Alarm E = False.
- **Full Strike (100% Size):** 1m DI+ > 30. Order: LIMIT at Ask * 1.001.
- **Scaled Strike (50% Starter):** 1m DI+ [25-30]. Order: LIMIT at Ask * 1.001.
- **Scale-In:** Add 50% only if (1m DI+ > 30) AND (New NHOD) AND (Alarm E = False).

---

## SECTION 3: THE WOUNDED BUFFALO (SHORT)

### PHASE 1 & 2: WEATHER & PERMITS
- **Weather:** QQQ(5m) < 9-EMA AND QQQ < 9:30 AM Anchor VWAP.
- **Permit:** Two consecutive 1m closes below Target Level (ORL for Strike 1 | NLOD for Strikes 2/3).
- **Volume Gate:** 1m Volume >= 100% of 55-bar rolling average (Required after 10:00 AM).

### PHASE 3: SIZING & EXECUTION
**Authority:** 5m DI- > 25. **Momentum:** 5m ADX > 20 AND Alarm E = False.
- **Full Strike (100% Size):** 1m DI- > 30. Order: LIMIT at Bid * 0.999.
- **Scaled Strike (50% Starter):** 1m DI- [25-30]. Order: LIMIT at Bid * 0.999.
- **Scale-In:** Add 50% only if (1m DI- > 30) AND (New NLOD) AND (Alarm E = False).

---

## SECTION 4: SHARED RULES & RISK MANAGEMENT

- **Entry Window:** 09:36:00 to 15:44:59 EST.
- **Hard Stop:** Immediate resting STOP MARKET at -$500 level.
- **Daily Circuit Breaker:** Halt all trading if session P&L reaches -$1,500.
- **EOD Flush:** Absolute Market Close at 15:49:59 EST.

---

## ADDENDUM: THE SENTINELS (EXIT PROTECTION)

- **ALARM A (Flash Move):** 1m price move > 1% against position -> MARKET EXIT.
- **ALARM B (Trend Death):** 5-minute candle across 5m 9-EMA -> MARKET EXIT.
- **ALARM C (Tiger Grip):** 3 consecutive 1m ADX declines -> RATCHET STOP ± 0.25%.
- **ALARM D (HVP Lock):** 5m ADX < 75% session peak (HWM) -> MARKET EXIT.
- **ALARM E (Divergence):** New extreme on lower RSI momentum -> RATCHET STOP ± 0.25%.

---

**End of original source.**
