"""Tiger Sovereign — local dashboard.

A simple, clean UI to track the project and run backtests with a visual of
where the bot entered and exited.

Run it:  uv run streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from tiger import batch, data
from tiger.backtest import (
    load_and_run_yfinance,
    run_backtest,
    summary_stats,
)

ROOT = Path(__file__).parent
ET_GREEN, ET_RED, ET_BLUE = "#16a34a", "#dc2626", "#2563eb"

st.set_page_config(page_title="Tiger Sovereign", page_icon="🐯", layout="wide")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _read(path: str) -> str:
    p = ROOT / path
    return p.read_text() if p.exists() else f"_(missing {path})_"


def price_chart(day_bars, result):
    """Candlestick of the traded day + opening range + entry/exit markers."""
    s = result.state
    fig = go.Figure(
        go.Candlestick(
            x=day_bars.index,
            open=day_bars["open"], high=day_bars["high"],
            low=day_bars["low"], close=day_bars["close"],
            name="price", increasing_line_color=ET_GREEN, decreasing_line_color=ET_RED,
        )
    )
    if s.orh is not None:
        fig.add_hline(y=s.orh, line_dash="dot", line_color=ET_BLUE,
                      annotation_text="ORH (open range high)")
    if s.orl is not None:
        fig.add_hline(y=s.orl, line_dash="dot", line_color=ET_BLUE,
                      annotation_text="ORL (open range low)")

    for t in result.trades:
        up = t.direction.value == "long"
        fig.add_trace(go.Scatter(
            x=[t.entry_time], y=[float(t.entry_price)], mode="markers",
            marker=dict(symbol="triangle-up" if up else "triangle-down",
                        size=15, color=ET_GREEN if up else ET_RED,
                        line=dict(width=1, color="white")),
            name=f"Entry S{t.strike_number} ({t.direction.value})",
        ))
        win = t.realized_pnl() > 0
        fig.add_trace(go.Scatter(
            x=[t.exit_time], y=[float(t.exit_price)], mode="markers",
            marker=dict(symbol="x", size=13,
                        color=ET_GREEN if win else ET_RED, line=dict(width=1)),
            name=f"Exit S{t.strike_number} ({t.exit_reason.value})",
        ))
    fig.update_layout(height=520, margin=dict(t=10, b=10),
                      xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=-0.12))
    return fig


def show_result(result, day_bars):
    stats = summary_stats(result)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Session P&L", f"${stats['total_pnl']:,.2f}")
    c2.metric("Trades", stats["trades"])
    c3.metric("Win rate", f"{stats['win_rate']:.0f}%" if stats["trades"] else "—")
    c4.metric("Strikes used", f"{stats['strikes']} / 3")

    if stats["circuit_broken"]:
        st.error("⚠️ Daily circuit breaker tripped (−$1,500 hit) — trading halted for the day.")

    st.plotly_chart(price_chart(day_bars, result), use_container_width=True)

    if result.trades:
        rows = [{
            "Strike": t.strike_number,
            "Direction": "▲ Long" if t.direction.value == "long" else "▼ Short",
            "Shares": t.shares,
            "Entry": f"{float(t.entry_price):.3f}",
            "Exit": f"{float(t.exit_price):.3f}",
            "Why it exited": t.exit_reason.value.replace("_", " "),
            "P&L": f"${float(t.realized_pnl()):,.2f}",
            "In at": t.entry_time.strftime("%H:%M"),
            "Out at": t.exit_time.strftime("%H:%M"),
        } for t in result.trades]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No trades — the filters never all lined up on this day. That's normal; "
                "the strategy sits out days without a clean setup.")


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
st.title("🐯 Tiger Sovereign")
st.caption("Intraday momentum trading bot — backtesting stage. Not trading real money.")

tab_run, tab_batch, tab_status, tab_spec = st.tabs(
    ["▶ Run a backtest", "📈 Batch test (the edge)", "📋 Project status", "📖 Strategy & open questions"]
)

with tab_run:
    st.subheader("Test the strategy on a real recent day")
    col_in, col_btn, col_demo = st.columns([2, 1, 1])
    ticker = col_in.text_input("Ticker", value="NVDA", label_visibility="collapsed",
                               placeholder="Ticker e.g. NVDA").strip().upper()
    run_real = col_btn.button("Run on real data", type="primary", use_container_width=True)
    run_demo = col_demo.button("Demo (fake day)", use_container_width=True)
    st.caption("Real data = free yfinance bars (last ~7 days, consolidated). "
               "Trades the most recent session; earlier days warm up the indicators.")

    if run_real and ticker:
        with st.spinner(f"Fetching {ticker} + QQQ and running the strategy…"):
            try:
                result, day_bars = load_and_run_yfinance(ticker)
                st.success(f"Ran {result.ticker} for {result.date}")
                show_result(result, day_bars)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Couldn't run {ticker}: {exc}\n\n"
                         "yfinance is often rate-limited — wait a moment and retry, "
                         "or use the Demo button.")
    elif run_demo:
        with st.spinner("Running the synthetic demo day…"):
            stock, qqq = data.synthetic_session()
            target = stock.index.normalize().unique()[-1]
            result = run_backtest(stock, qqq, "SYNTH")
            show_result(result, stock[stock.index.normalize() == target])

with tab_batch:
    st.subheader("Does the strategy actually make money?")
    st.caption("Runs the strategy across every recent session for each ticker and totals it up. "
               "This is the real test of edge — one day means nothing.")
    tickers_raw = st.text_input(
        "Tickers (comma-separated)", value="NVDA, TSLA, AMD, AAPL, META",
        help="A few liquid momentum names. Each is run over its last ~5 sessions.",
    )
    if st.button("Run batch", type="primary"):
        tickers = [t for t in tickers_raw.split(",") if t.strip()]
        with st.spinner(f"Running {len(tickers)} tickers across their recent sessions…"):
            try:
                br = batch.run_batch(tickers)
                stats = br.stats()
                if br.skipped:
                    st.warning(f"Couldn't load (likely rate-limited): {', '.join(br.skipped)}")

                pf = stats["profit_factor"]
                pf_txt = "∞" if pf == float("inf") else f"{pf:.2f}"
                a, b, c, d = st.columns(4)
                a.metric("Total P&L", f"${stats['total_pnl']:,.2f}")
                b.metric("Expectancy / trade", f"${stats['expectancy']:,.2f}",
                         help="Average $ per trade over the long run. The number that matters most.")
                c.metric("Win rate", f"{stats['win_rate']:.0f}%")
                d.metric("Profit factor", pf_txt,
                         help="Gross winnings ÷ gross losses. Above 1.0 = profitable.")
                e, f, g, h = st.columns(4)
                e.metric("Trades", stats["trades"])
                f.metric("Avg win", f"${stats['avg_win']:,.2f}")
                g.metric("Avg loss", f"${stats['avg_loss']:,.2f}")
                h.metric("Sessions", f"{stats['sessions_with_trades']}/{stats['sessions']} traded")

                # verdict
                exp = stats["expectancy"]
                if stats["trades"] == 0:
                    st.info("No trades fired across this batch.")
                elif exp > 0:
                    st.success(f"📈 Positive expectancy on this sample: +${exp:,.2f}/trade. "
                               "Encouraging — but the free-data sample is tiny. Needs deeper history before trusting it.")
                else:
                    st.error(f"📉 Negative expectancy on this sample: ${exp:,.2f}/trade. "
                             "On this slice it loses money. Worth investigating before going further.")

                times, cum = br.equity_curve()
                if times:
                    eq = go.Figure(go.Scatter(x=times, y=cum, mode="lines+markers",
                                              line=dict(color=ET_BLUE, width=2)))
                    eq.add_hline(y=0, line_dash="dot", line_color="gray")
                    eq.update_layout(height=340, margin=dict(t=10, b=10),
                                     title="Equity curve (cumulative P&L by trade)")
                    st.plotly_chart(eq, use_container_width=True)

                if stats["exit_reasons"]:
                    er = stats["exit_reasons"]
                    bar = go.Figure(go.Bar(x=list(er.keys()), y=list(er.values()), marker_color=ET_BLUE))
                    bar.update_layout(height=300, margin=dict(t=10, b=10),
                                      title="How trades exited")
                    st.plotly_chart(bar, use_container_width=True)

                rows = br.trade_rows()
                if rows:
                    st.dataframe(
                        [{
                            "Ticker": r["ticker"], "Date": r["date"],
                            "Dir": "▲" if r["direction"] == "long" else "▼",
                            "Entry": f"{r['entry']:.2f}", "Exit": f"{r['exit']:.2f}",
                            "Exit reason": r["exit_reason"].replace("_", " "),
                            "P&L": f"${r['pnl']:,.2f}",
                        } for r in rows],
                        use_container_width=True, hide_index=True,
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Batch failed: {exc}\n\nyfinance is often rate-limited — wait and retry.")

    st.caption("⚠️ Free data = ~5 sessions/ticker. This is a smoke test of edge, not a verdict. "
               "A real expectancy study needs the deeper history from Phase 2's paid data.")

with tab_status:
    st.subheader("Where the project is")
    st.markdown(_read("ROADMAP.md"))

with tab_spec:
    left, right = st.columns(2)
    with left:
        st.subheader("Open questions for the author")
        st.markdown(_read("docs/OPEN_QUESTIONS.md"))
    with right:
        st.subheader("The strategy (original source)")
        st.markdown(_read("docs/STRATEGY_SPEC_ORIGINAL.md"))
