# Tiger Sovereign — Trading Bot

Automated intraday momentum trading bot. Executes the "Tiger Sovereign" opening-range-breakout strategy on US equities via Alpaca. **Paper trading first, real money much later.**

## Context you need every session

- **The owner (Julian) does not trade.** Someone handed him this strategy to automate. Own all trading internals; never make him learn what ADX/VWAP/etc. mean. Explain decisions in plain English.
- **The strategy is the boss.** `docs/STRATEGY_SPEC.md` is canonical and supplied by the strategy author. Match it exactly. Do not "improve" the strategy.
- **Never guess on ambiguity.** If the spec is silent or unclear, it goes in `docs/OPEN_QUESTIONS.md`, gets a code default tagged `# OPEN-Q#`, and Julian relays it to the strategy author. Do not silently pick behavior that affects real-money trades.
- **Where we are** lives in `ROADMAP.md`. Update statuses as modules land.

## How we build

- **Backtest first.** Prove the edge on free historical data before any live engine or paid data. (Deviation from the spec's build order, agreed with owner.)
- **Phase-gated.** Phase 1 (backtest, $0) → gate → Phase 2 (paper, paid data) → gate → Phase 3 (real money). Don't skip gates.
- **Module by module, tested.** Each module gets unit tests before the next is built. Indicators get validated against TradingView numbers.
- **Money correctness:** `decimal.Decimal` for all price/P&L math. DST-aware Eastern Time, never naive datetimes.
- **Mock the broker first.** No live Alpaca calls until logic is proven on synthetic/historical data.

## Stack

- Python 3.11, managed with **uv** (`uv run`, `uv add`, `uv sync`).
- Indicators: **pandas-ta** to start; hand-roll Wilder's smoothing if it doesn't match TradingView.
- Broker: Alpaca (paper). Scanner data: Polygon (Phase 2 only).
- Persistence: SQLite. Logs: JSON + Slack (Phase 2).

## Layout

```
docs/STRATEGY_SPEC.md   canonical strategy (don't edit intent)
docs/OPEN_QUESTIONS.md  ambiguities for the strategy author
ROADMAP.md              phase tracker — current status
src/tiger/              the package (modules added as built)
tests/                  unit tests, mirror src/tiger
data/                   historical bars + sqlite (gitignored)
```

## Commands

- `uv run pytest` — run tests
- `uv add <pkg>` — add a dependency
- `uv run python -m tiger.<module>` — run a module
