# Tiger Sovereign

An automated intraday momentum trading bot for US equities. It hunts opening-range breakouts on pre-market gap stocks, enters with stacked confirmation filters, and manages exits with six independent "sentinel" alarms. Deterministic rules — no AI prediction.

**Status:** Phase 1 (backtesting). Not trading real money. See [`ROADMAP.md`](ROADMAP.md).

## Quick start

```bash
uv sync                 # install dependencies into .venv
uv run pytest           # run the test suite
```

## Docs

- [`docs/STRATEGY_SPEC.md`](docs/STRATEGY_SPEC.md) — the canonical strategy (the rulebook).
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — ambiguities awaiting the strategy author.
- [`ROADMAP.md`](ROADMAP.md) — phased build plan + current status.
- [`CLAUDE.md`](CLAUDE.md) — how this project is built.

## Build philosophy

Backtest first. Prove the strategy makes money on free historical data before building the live engine or paying for market-data subscriptions. Three phases, each gated: backtest → live paper → real money.

## Configuration

Copy `.env.example` to `.env` and fill in keys (none required for Phase 1 backtesting).

```bash
cp .env.example .env
```
