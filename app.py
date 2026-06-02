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
from tiger import logger as event_log
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

tab_live, tab_run, tab_batch, tab_status, tab_spec = st.tabs(
    ["🔴 Live Trading", "▶ Run a backtest", "📈 Batch test (the edge)", "📋 Project status", "📖 Strategy & open questions"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# LIVE TRADING TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_live:
    st.subheader("Live paper trading — today's session")
    st.caption("Refreshes every 10 seconds while the bot is running. Start the bot with: `uv run python run.py`")

    auto_refresh = st.toggle("Auto-refresh", value=True)
    if auto_refresh:
        import time as _time
        _time.sleep(0)   # yields; Streamlit will rerun on next cycle
        st.empty()

    events = event_log.read_today()

    if not events:
        st.info("No activity yet today. Run `uv run python run.py` in your terminal to start the bot.")
    else:
        # ── Scan results ────────────────────────────────────────────────────
        scan_events = [e for e in events if e["type"] == "scan"]
        if scan_events:
            latest_scan = scan_events[-1]
            candidates = latest_scan.get("candidates", [])
            st.markdown("### Today's pre-market scan")
            if not candidates:
                st.warning("Scanner ran but found no gap candidates with news today.")
            else:
                for c in candidates:
                    sign = "+" if c["gap_pct"] > 0 else ""
                    direction_emoji = "▲" if c["direction"] == "long" else "▼"
                    st.markdown(
                        f"**{c['ticker']}** &nbsp; {direction_emoji} {sign}{c['gap_pct']:.1f}% gap &nbsp;|&nbsp; "
                        f"prev close {c['prev_close']:.2f} → pre-market {c['premarket_price']:.2f}"
                    )
                    for h in c.get("headlines", [])[:2]:
                        st.caption(f"  📰 {h}")

        st.divider()

        # ── Current position ────────────────────────────────────────────────
        entries = [e for e in events if e["type"] == "entry"]
        exits = [e for e in events if e["type"] == "exit"]
        open_strike = None
        if len(entries) > len(exits):
            open_strike = entries[-1]

        if open_strike:
            st.markdown("### Open position")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Ticker", open_strike["ticker"])
            col2.metric("Direction", open_strike["direction"].upper())
            col3.metric("Entry price", f"${open_strike['limit_price']:.2f}")
            col4.metric("Stop price", f"${open_strike['stop_price']:.2f}")

            ratchets = [e for e in events if e["type"] == "ratchet"
                        and e["ts"] > open_strike["ts"]]
            if ratchets:
                latest_r = ratchets[-1]
                st.caption(
                    f"Stop ratcheted {len(ratchets)}x — latest: "
                    f"${latest_r['old_stop']:.2f} → ${latest_r['new_stop']:.2f} ({latest_r['alarm']})"
                )
            scale_ins = [e for e in events if e["type"] == "scale_in"
                         and e["ts"] > open_strike["ts"]]
            if scale_ins:
                si = scale_ins[-1]
                st.caption(f"Scaled in: +{si['add_qty']} shares @ blended ${si['blended_price']:.2f}")

            st.divider()

        # ── Trade history (today) ───────────────────────────────────────────
        if exits:
            st.markdown("### Trades today")
            daily_pnl = exits[-1]["daily_pnl"]
            pnl_color = ET_GREEN if daily_pnl >= 0 else ET_RED
            st.markdown(
                f"**Daily P&L: <span style='color:{pnl_color}'>${daily_pnl:+.2f}</span>**",
                unsafe_allow_html=True,
            )

            rows = []
            for ex in exits:
                matching_entry = next(
                    (e for e in entries if e["ticker"] == ex["ticker"]
                     and e["ts"] <= ex["ts"]), None
                )
                rows.append({
                    "Ticker": ex["ticker"],
                    "Dir": "▲" if ex["direction"] == "long" else "▼",
                    "Entry $": f"{ex['entry_price']:.2f}",
                    "Exit $": f"{ex['exit_price']:.2f}",
                    "Qty": ex["qty"],
                    "P&L": f"${ex['pnl']:+.2f}",
                    "Exit reason": ex["reason"].replace("_", " "),
                    "Time": ex["ts"][11:16],
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

            # Mini equity curve
            cumulative = 0.0
            curve_x, curve_y = [], []
            for ex in sorted(exits, key=lambda e: e["ts"]):
                cumulative += ex["pnl"]
                curve_x.append(ex["ts"][11:16])
                curve_y.append(cumulative)
            if len(curve_x) > 1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=curve_x, y=curve_y, mode="lines+markers",
                    line=dict(color=ET_GREEN if curve_y[-1] >= 0 else ET_RED, width=2),
                    fill="tozeroy",
                    fillcolor="rgba(22,163,74,0.1)" if curve_y[-1] >= 0 else "rgba(220,38,38,0.1)",
                ))
                fig.update_layout(
                    height=200, margin=dict(l=0, r=0, t=10, b=0),
                    yaxis_title="P&L ($)", xaxis_title="",
                    showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig, use_container_width=True)

        elif not open_strike:
            st.info("Bot is running — no trades taken yet today.")

        st.divider()

        # ── Decision log ────────────────────────────────────────────────────
        st.markdown("### Decision log")
        st.caption("Every entry, exit, ratchet, and scale-in — with the indicator values that triggered it.")

        log_types = {"entry", "exit", "ratchet", "scale_in", "circuit_break"}
        decision_events = [e for e in events if e["type"] in log_types]

        if not decision_events:
            st.caption("No decisions yet.")
        else:
            for ev in reversed(decision_events[-50:]):
                t = ev["ts"][11:16]
                etype = ev["type"]
                if etype == "entry":
                    ind = ev.get("ind", {})
                    adx = ind.get("adx_5m", "?")
                    di = ind.get("di_plus_1m" if ev["direction"] == "long" else "di_minus_1m", "?")
                    st.success(
                        f"**{t}  ENTRY {ev['direction'].upper()} {ev['ticker']}** — "
                        f"{ev['qty']} shares @ ${ev['limit_price']:.2f}  |  "
                        f"stop ${ev['stop_price']:.2f}  |  "
                        f"Strike {ev['strike_num']} ({'full' if ev['full_size'] else 'half'} size)  |  "
                        f"ADX5m={adx}  DI={di}"
                    )
                elif etype == "exit":
                    color_fn = st.success if ev["pnl"] >= 0 else st.error
                    color_fn(
                        f"**{t}  EXIT {ev['direction'].upper()} {ev['ticker']}** — "
                        f"@ ${ev['exit_price']:.2f}  |  "
                        f"P&L **${ev['pnl']:+.2f}**  |  reason: {ev['reason'].replace('_', ' ')}"
                    )
                elif etype == "ratchet":
                    st.warning(
                        f"**{t}  RATCHET {ev['ticker']}** — "
                        f"stop ${ev['old_stop']:.2f} → ${ev['new_stop']:.2f}  ({ev['alarm']})"
                    )
                elif etype == "scale_in":
                    st.info(
                        f"**{t}  SCALE-IN {ev['ticker']}** — "
                        f"+{ev['add_qty']} shares  blended ${ev['blended_price']:.2f}  "
                        f"new stop ${ev['new_stop']:.2f}"
                    )
                elif etype == "circuit_break":
                    st.error(f"**{t}  CIRCUIT BREAKER** — daily loss limit hit. No more trades today.")

        st.divider()

        # ── What the bot is learning (all-time paper stats) ─────────────────
        st.markdown("### What the bot is learning (all paper trades)")
        st.caption("Accumulates across every day the bot has run.")

        all_events = event_log.read_all()
        all_exits = [e for e in all_events if e["type"] == "exit"]

        if len(all_exits) < 2:
            st.caption("Need at least 2 completed trades to show patterns.")
        else:
            wins = [e for e in all_exits if e["pnl"] > 0]
            losses = [e for e in all_exits if e["pnl"] <= 0]
            total_pnl = sum(e["pnl"] for e in all_exits)
            win_rate = len(wins) / len(all_exits) * 100

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total paper trades", len(all_exits))
            m2.metric("Win rate", f"{win_rate:.0f}%")
            m3.metric("Total paper P&L", f"${total_pnl:+,.2f}")
            m4.metric("Avg trade", f"${total_pnl/len(all_exits):+.2f}")

            # Exit reasons breakdown
            from collections import Counter
            reasons = Counter(e["reason"] for e in all_exits)
            st.markdown("**Why trades ended:**")
            reason_data = [
                {"Exit reason": r.replace("_", " "), "Count": c,
                 "Avg P&L": f"${sum(e['pnl'] for e in all_exits if e['reason'] == r)/c:+.2f}"}
                for r, c in reasons.most_common()
            ]
            st.dataframe(reason_data, use_container_width=True, hide_index=True)

            # Direction breakdown
            long_exits = [e for e in all_exits if e["direction"] == "long"]
            short_exits = [e for e in all_exits if e["direction"] == "short"]
            if long_exits and short_exits:
                st.markdown("**Long vs Short:**")
                dir_data = [
                    {"Direction": "Long (Bison)",
                     "Trades": len(long_exits),
                     "Win rate": f"{sum(1 for e in long_exits if e['pnl'] > 0)/len(long_exits)*100:.0f}%",
                     "Total P&L": f"${sum(e['pnl'] for e in long_exits):+,.2f}"},
                    {"Direction": "Short (Wounded Buffalo)",
                     "Trades": len(short_exits),
                     "Win rate": f"{sum(1 for e in short_exits if e['pnl'] > 0)/len(short_exits)*100:.0f}%",
                     "Total P&L": f"${sum(e['pnl'] for e in short_exits):+,.2f}"},
                ]
                st.dataframe(dir_data, use_container_width=True, hide_index=True)

    if auto_refresh:
        import time as _time
        _time.sleep(10)
        st.rerun()


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
