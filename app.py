"""Tiger Sovereign — trading dashboard."""
from __future__ import annotations

import time as _time
from collections import Counter
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from tiger import batch, data
from tiger import logger as event_log
from tiger.backtest import load_and_run_yfinance, run_backtest, summary_stats

ROOT = Path(__file__).parent

st.set_page_config(page_title="TIGER SOVEREIGN", page_icon="🐯", layout="wide")

# ── Futuristic CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap');

html, body, [class*="css"] { font-family: 'Share Tech Mono', monospace; }

.stApp { background-color: #06061a; }

/* ── Header ── */
.tiger-header {
    background: linear-gradient(90deg, #06061a 0%, #0d0d35 50%, #06061a 100%);
    border-bottom: 1px solid rgba(0,255,200,0.2);
    padding: 18px 0 14px 0;
    margin-bottom: 24px;
    text-align: center;
}
.tiger-title {
    font-family: 'Orbitron', sans-serif;
    font-size: 2.4rem;
    font-weight: 900;
    letter-spacing: 0.25em;
    background: linear-gradient(90deg, #00ffc8, #7c3aed, #00ffc8);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: shimmer 4s linear infinite;
}
@keyframes shimmer { to { background-position: 200% center; } }

.live-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(255,45,85,0.15); border: 1px solid rgba(255,45,85,0.4);
    border-radius: 20px; padding: 3px 12px;
    font-size: 0.7rem; letter-spacing: 0.15em; color: #ff2d55;
}
.live-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: #ff2d55;
    animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 6px #ff2d55; }
    50% { opacity: 0.3; box-shadow: none; }
}

/* ── Cards ── */
.card {
    background: linear-gradient(135deg, rgba(13,13,45,0.9) 0%, rgba(8,8,30,0.9) 100%);
    border: 1px solid rgba(0,255,200,0.15);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 0 30px rgba(0,255,200,0.04), inset 0 0 30px rgba(0,0,80,0.2);
    position: relative; overflow: hidden;
}
.card::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,255,200,0.5), transparent);
}

.card-danger {
    border-color: rgba(255,45,85,0.3);
    box-shadow: 0 0 30px rgba(255,45,85,0.06);
}
.card-danger::before {
    background: linear-gradient(90deg, transparent, rgba(255,45,85,0.5), transparent);
}
.card-warning {
    border-color: rgba(255,184,0,0.3);
    box-shadow: 0 0 30px rgba(255,184,0,0.06);
}

.card-label {
    font-size: 0.65rem; letter-spacing: 0.2em;
    color: rgba(0,255,200,0.5); text-transform: uppercase;
    margin-bottom: 6px;
}
.card-value {
    font-family: 'Orbitron', sans-serif;
    font-size: 1.8rem; font-weight: 700;
    color: #00ffc8;
}
.card-value-red { color: #ff2d55; }
.card-value-sm { font-size: 1.1rem; }
.card-sub { font-size: 0.75rem; color: rgba(180,190,255,0.5); margin-top: 4px; }

/* ── Ticker badge ── */
.ticker-badge {
    display: inline-block;
    background: rgba(0,255,200,0.08);
    border: 1px solid rgba(0,255,200,0.3);
    border-radius: 6px;
    padding: 8px 16px;
    margin: 6px 4px;
    font-family: 'Orbitron', sans-serif;
    font-size: 1.1rem; font-weight: 700; color: #00ffc8;
}
.ticker-gap-up { color: #00ff88; border-color: rgba(0,255,136,0.4); }
.ticker-gap-down { color: #ff2d55; border-color: rgba(255,45,85,0.4); }
.ticker-gap-pct { font-size: 0.8rem; color: rgba(255,255,255,0.5); margin-left: 8px; }

/* ── News headline ── */
.headline {
    font-size: 0.75rem; color: rgba(180,190,255,0.65);
    border-left: 2px solid rgba(0,255,200,0.3);
    padding-left: 10px; margin: 4px 0;
    font-family: 'Share Tech Mono', monospace;
}

/* ── Decision log ── */
.log-entry {
    font-size: 0.78rem; font-family: 'Share Tech Mono', monospace;
    padding: 8px 12px; border-radius: 4px; margin: 4px 0;
    border-left: 3px solid;
}
.log-entry-entry {
    background: rgba(0,255,136,0.05);
    border-color: #00ff88; color: #b0ffda;
}
.log-entry-exit-win {
    background: rgba(0,255,136,0.05);
    border-color: #00ffc8; color: #a0f0d0;
}
.log-entry-exit-loss {
    background: rgba(255,45,85,0.05);
    border-color: #ff2d55; color: #ffb0b8;
}
.log-entry-ratchet {
    background: rgba(255,184,0,0.05);
    border-color: #ffb800; color: #ffe090;
}
.log-entry-scale {
    background: rgba(124,58,237,0.08);
    border-color: #7c3aed; color: #c4b0ff;
}
.log-entry-circuit {
    background: rgba(255,45,85,0.12);
    border-color: #ff2d55; color: #ff2d55;
    font-weight: 700;
}
.log-time { color: rgba(0,255,200,0.6); margin-right: 10px; }

/* ── Divider ── */
.neon-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,255,200,0.2), transparent);
    margin: 24px 0;
}

/* ── Section header ── */
.section-header {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.75rem; font-weight: 700;
    letter-spacing: 0.25em; text-transform: uppercase;
    color: rgba(0,255,200,0.6);
    margin-bottom: 14px;
}

/* ── Streamlit overrides ── */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(13,13,45,0.6);
    border-bottom: 1px solid rgba(0,255,200,0.15);
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.75rem; letter-spacing: 0.1em;
    color: rgba(180,190,255,0.5) !important;
    background: transparent !important;
    border: none !important;
    padding: 10px 20px;
}
.stTabs [aria-selected="true"] {
    color: #00ffc8 !important;
    border-bottom: 2px solid #00ffc8 !important;
}
[data-testid="stMetricValue"] { font-family: 'Orbitron', monospace; font-size: 1.4rem; }
[data-testid="stMetricLabel"] { font-size: 0.65rem; letter-spacing: 0.15em; opacity: 0.6; }
.stButton > button {
    font-family: 'Share Tech Mono', monospace; letter-spacing: 0.1em;
    border: 1px solid rgba(0,255,200,0.4) !important;
    background: rgba(0,255,200,0.06) !important;
    color: #00ffc8 !important;
}
.stButton > button:hover {
    background: rgba(0,255,200,0.14) !important;
    box-shadow: 0 0 16px rgba(0,255,200,0.2);
}
.stDataFrame { border: 1px solid rgba(0,255,200,0.1) !important; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ── Page header ──────────────────────────────────────────────────────────────
st.markdown("""
<div class="tiger-header">
    <div class="tiger-title">TIGER SOVEREIGN</div>
    <div style="margin-top:8px;">
        <span class="live-badge"><span class="live-dot"></span>PAPER TRADING ACTIVE</span>
    </div>
    <div style="font-size:0.65rem;color:rgba(180,190,255,0.3);margin-top:8px;letter-spacing:0.2em;">
        INTRADAY MOMENTUM SYSTEM &nbsp;|&nbsp; US EQUITIES &nbsp;|&nbsp; ALPACA PAPER
    </div>
</div>
""", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_live, tab_run, tab_batch, tab_status, tab_spec = st.tabs([
    "◉ LIVE",
    "▷ BACKTEST",
    "▤ BATCH",
    "◈ STATUS",
    "◎ STRATEGY",
])


# ── helpers ───────────────────────────────────────────────────────────────────
def _read(path: str) -> str:
    p = ROOT / path
    return p.read_text() if p.exists() else f"_(missing {path})_"


def _card(label: str, value: str, sub: str = "", danger: bool = False, warn: bool = False) -> str:
    cls = "card-danger" if danger else ("card-warning" if warn else "")
    val_cls = "card-value-red" if danger else "card-value"
    return f"""
    <div class="card {cls}">
        <div class="card-label">{label}</div>
        <div class="{val_cls}">{value}</div>
        {"<div class='card-sub'>" + sub + "</div>" if sub else ""}
    </div>"""


def _log_html(events: list[dict]) -> str:
    lines = []
    for ev in reversed(events[-60:]):
        t = ev["ts"][11:16]
        etype = ev["type"]
        if etype == "entry":
            ind = ev.get("ind", {})
            adx = f"{ind.get('adx_5m', '?')}"
            lines.append(
                f'<div class="log-entry log-entry-entry">'
                f'<span class="log-time">{t}</span>'
                f'ENTRY &nbsp; {ev["direction"].upper()} &nbsp; {ev["ticker"]} &nbsp;'
                f'@ ${ev["limit_price"]:.2f} &nbsp;|&nbsp; '
                f'stop ${ev["stop_price"]:.2f} &nbsp;|&nbsp; '
                f'strike {ev["strike_num"]} ({("FULL" if ev["full_size"] else "HALF")}) &nbsp;|&nbsp; '
                f'ADX5={adx}'
                f'</div>'
            )
        elif etype == "exit":
            win = ev["pnl"] >= 0
            cls = "log-entry-exit-win" if win else "log-entry-exit-loss"
            pnl_str = f'+${ev["pnl"]:.2f}' if win else f'-${abs(ev["pnl"]):.2f}'
            lines.append(
                f'<div class="log-entry {cls}">'
                f'<span class="log-time">{t}</span>'
                f'EXIT &nbsp; {ev["direction"].upper()} &nbsp; {ev["ticker"]} &nbsp;'
                f'@ ${ev["exit_price"]:.2f} &nbsp;|&nbsp; '
                f'P&L <strong>{pnl_str}</strong> &nbsp;|&nbsp; '
                f'{ev["reason"].replace("_", " ")}'
                f'</div>'
            )
        elif etype == "ratchet":
            lines.append(
                f'<div class="log-entry log-entry-ratchet">'
                f'<span class="log-time">{t}</span>'
                f'RATCHET &nbsp; {ev["ticker"]} &nbsp;'
                f'stop ${ev["old_stop"]:.2f} → ${ev["new_stop"]:.2f} &nbsp;({ev["alarm"].upper()})'
                f'</div>'
            )
        elif etype == "scale_in":
            lines.append(
                f'<div class="log-entry log-entry-scale">'
                f'<span class="log-time">{t}</span>'
                f'SCALE-IN &nbsp; {ev["ticker"]} &nbsp;'
                f'+{ev["add_qty"]} shares @ blended ${ev["blended_price"]:.2f} &nbsp;|&nbsp; '
                f'new stop ${ev["new_stop"]:.2f}'
                f'</div>'
            )
        elif etype == "circuit_break":
            lines.append(
                f'<div class="log-entry log-entry-circuit">'
                f'<span class="log-time">{t}</span>'
                f'⚡ CIRCUIT BREAKER — daily loss limit hit. Trading halted.'
                f'</div>'
            )
    return "\n".join(lines) if lines else '<div style="color:rgba(180,190,255,0.3);font-size:0.8rem;">No decisions yet.</div>'


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_live:
    auto_refresh = st.toggle("Auto-refresh (10s)", value=True, key="ar")
    events = event_log.read_today()
    all_events = event_log.read_all()

    entries = [e for e in events if e["type"] == "entry"]
    exits = [e for e in events if e["type"] == "exit"]
    open_strike = entries[-1] if len(entries) > len(exits) else None
    all_exits = [e for e in all_events if e["type"] == "exit"]

    # Today's P&L: pull the REAL account number from Alpaca (equity - last_equity).
    # The per-engine log estimates measure from limit prices and silo by ticker,
    # so they diverge from the true account P&L. Fall back to the estimate if
    # Alpaca is unreachable.
    daily_pnl_source = "Alpaca (real)"
    try:
        from tiger import broker
        daily_pnl = float(broker.get_account_pnl())
    except Exception:
        daily_pnl = sum(e["pnl"] for e in exits)
        daily_pnl_source = "estimate"

    # ── Top metrics row ──────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    pnl_color = "card-value" if daily_pnl >= 0 else "card-value card-value-red"
    pnl_sign = "+" if daily_pnl >= 0 else ""
    c1.markdown(_card("TODAY P&L", f"{pnl_sign}${daily_pnl:,.2f}",
                      sub=daily_pnl_source, danger=daily_pnl < 0), unsafe_allow_html=True)
    c2.markdown(_card("TRADES TODAY", str(len(exits)),
                      sub=f"{len(entries) - len(exits)} open"), unsafe_allow_html=True)
    win_today = len([e for e in exits if e["pnl"] > 0])
    wr_today = f"{win_today/len(exits)*100:.0f}%" if exits else "—"
    c3.markdown(_card("WIN RATE", wr_today,
                      sub=f"{win_today}W / {len(exits)-win_today}L"), unsafe_allow_html=True)
    all_pnl = sum(e["pnl"] for e in all_exits)
    c4.markdown(_card("ALL-TIME P&L", f"${all_pnl:+,.2f}",
                      sub=f"{len(all_exits)} total paper trades",
                      danger=all_pnl < 0), unsafe_allow_html=True)
    all_wr = f"{sum(1 for e in all_exits if e['pnl']>0)/len(all_exits)*100:.0f}%" if all_exits else "—"
    c5.markdown(_card("ALL-TIME WIN RATE", all_wr), unsafe_allow_html=True)

    st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)

    # ── Two column layout: left = scan + position, right = log ───────────────
    left, right = st.columns([1, 1.4])

    with left:
        # Scan results
        scan_events = [e for e in events if e["type"] == "scan"]
        st.markdown('<div class="section-header">Pre-Market Scan</div>', unsafe_allow_html=True)
        if not scan_events:
            st.markdown('<div style="color:rgba(180,190,255,0.3);font-size:0.8rem;">Scanner hasn\'t run yet today.</div>', unsafe_allow_html=True)
        else:
            candidates = scan_events[-1].get("candidates", [])
            scan_time = scan_events[-1]["ts"][11:16]
            if not candidates:
                st.markdown(f'<div style="color:rgba(255,184,0,0.6);font-size:0.8rem;">Scan at {scan_time} — no gap candidates found.</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="color:rgba(0,255,200,0.4);font-size:0.7rem;margin-bottom:10px;">SCANNED AT {scan_time} ET</div>', unsafe_allow_html=True)
                for c in candidates:
                    sign = "+" if c["gap_pct"] > 0 else ""
                    dir_cls = "ticker-gap-up" if c["gap_pct"] > 0 else "ticker-gap-down"
                    arrow = "▲" if c["gap_pct"] > 0 else "▼"
                    headlines_html = "".join(
                        f'<div class="headline">📰 {h[:90]}</div>'
                        for h in c.get("headlines", [])[:2]
                    )
                    st.markdown(f"""
                    <div class="card" style="padding:14px;margin-bottom:10px;">
                        <span class="ticker-badge {dir_cls}">{c['ticker']}</span>
                        <span style="font-size:0.95rem;color:{'#00ff88' if c['gap_pct']>0 else '#ff2d55'};">
                            {arrow} {sign}{c['gap_pct']:.1f}%
                        </span>
                        <span style="font-size:0.72rem;color:rgba(180,190,255,0.4);margin-left:10px;">
                            {c['prev_close']:.2f} → {c['premarket_price']:.2f}
                        </span>
                        <div style="margin-top:8px;">{headlines_html}</div>
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)

        # Open position
        st.markdown('<div class="section-header">Open Position</div>', unsafe_allow_html=True)
        if open_strike:
            ratchets = [e for e in events if e["type"] == "ratchet" and e["ts"] > open_strike["ts"]]
            current_stop = ratchets[-1]["new_stop"] if ratchets else open_strike["stop_price"]
            dir_color = "#00ff88" if open_strike["direction"] == "long" else "#ff2d55"
            arrow = "▲" if open_strike["direction"] == "long" else "▼"
            st.markdown(f"""
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span class="ticker-badge" style="font-size:1.4rem;">{open_strike['ticker']}</span>
                    <span style="font-family:Orbitron;font-size:1.1rem;color:{dir_color};">
                        {arrow} {open_strike['direction'].upper()}
                    </span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px;">
                    <div>
                        <div class="card-label">ENTRY</div>
                        <div class="card-value card-value-sm">${open_strike['limit_price']:.2f}</div>
                    </div>
                    <div>
                        <div class="card-label">STOP</div>
                        <div class="card-value card-value-sm card-value-red">${current_stop:.2f}</div>
                    </div>
                    <div>
                        <div class="card-label">SHARES</div>
                        <div class="card-value card-value-sm">{open_strike['qty']}</div>
                    </div>
                    <div>
                        <div class="card-label">STRIKE</div>
                        <div class="card-value card-value-sm">{'FULL' if open_strike['full_size'] else 'HALF'} #{open_strike['strike_num']}</div>
                    </div>
                </div>
                {"<div style='margin-top:10px;font-size:0.72rem;color:rgba(255,184,0,0.7);'>Stop ratcheted " + str(len(ratchets)) + "x</div>" if ratchets else ""}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown('<div style="color:rgba(180,190,255,0.3);font-size:0.8rem;">No open position.</div>', unsafe_allow_html=True)

        st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)

        # Today's trades
        st.markdown('<div class="section-header">Trades Today</div>', unsafe_allow_html=True)
        if exits:
            # Equity curve
            cumulative, cx, cy = 0.0, [], []
            for ex in sorted(exits, key=lambda e: e["ts"]):
                cumulative += ex["pnl"]
                cx.append(ex["ts"][11:16])
                cy.append(cumulative)
            if len(cx) > 1:
                line_color = "#00ffc8" if cy[-1] >= 0 else "#ff2d55"
                fill_color = "rgba(0,255,200,0.08)" if cy[-1] >= 0 else "rgba(255,45,85,0.08)"
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=cx, y=cy, mode="lines+markers",
                    line=dict(color=line_color, width=2),
                    marker=dict(size=6, color=line_color,
                                line=dict(width=1, color="rgba(0,0,0,0.5)")),
                    fill="tozeroy", fillcolor=fill_color,
                ))
                fig.update_layout(
                    height=160, margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False, color="rgba(180,190,255,0.3)"),
                    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.04)",
                               color="rgba(180,190,255,0.3)", tickprefix="$"),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

            rows = [{
                "Ticker": e["ticker"],
                "Dir": "▲" if e["direction"] == "long" else "▼",
                "Entry": f"${e['entry_price']:.2f}",
                "Exit": f"${e['exit_price']:.2f}",
                "P&L": f"${e['pnl']:+.2f}",
                "Reason": e["reason"].replace("_", " "),
                "Time": e["ts"][11:16],
            } for e in exits]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.markdown('<div style="color:rgba(180,190,255,0.3);font-size:0.8rem;">No completed trades yet.</div>', unsafe_allow_html=True)

    with right:
        # Decision log
        st.markdown('<div class="section-header">Decision Log</div>', unsafe_allow_html=True)
        decision_types = {"entry", "exit", "ratchet", "scale_in", "circuit_break"}
        decision_events = [e for e in events if e["type"] in decision_types]
        st.markdown(
            f'<div style="height:420px;overflow-y:auto;padding-right:4px;">{_log_html(decision_events)}</div>',
            unsafe_allow_html=True
        )

        st.markdown('<div class="neon-divider"></div>', unsafe_allow_html=True)

        # What the bot is learning
        st.markdown('<div class="section-header">What the Bot is Learning</div>', unsafe_allow_html=True)
        if len(all_exits) < 2:
            st.markdown('<div style="color:rgba(180,190,255,0.3);font-size:0.8rem;">Need 2+ completed paper trades to show patterns.</div>', unsafe_allow_html=True)
        else:
            # Exit reasons breakdown
            reasons = Counter(e["reason"] for e in all_exits)
            reason_rows = []
            for r, count in reasons.most_common():
                pnls = [e["pnl"] for e in all_exits if e["reason"] == r]
                wins = sum(1 for p in pnls if p > 0)
                reason_rows.append({
                    "Exit reason": r.replace("_", " "),
                    "Count": count,
                    "Win%": f"{wins/count*100:.0f}%",
                    "Avg P&L": f"${sum(pnls)/count:+.2f}",
                })
            st.markdown('<div style="font-size:0.7rem;color:rgba(0,255,200,0.5);margin-bottom:6px;letter-spacing:0.1em;">WHY TRADES END</div>', unsafe_allow_html=True)
            st.dataframe(reason_rows, use_container_width=True, hide_index=True)

            # Long vs short
            long_exits = [e for e in all_exits if e["direction"] == "long"]
            short_exits = [e for e in all_exits if e["direction"] == "short"]
            if long_exits or short_exits:
                dir_rows = []
                for label, group in [("▲ Long (Bison)", long_exits), ("▼ Short (Buffalo)", short_exits)]:
                    if group:
                        w = sum(1 for e in group if e["pnl"] > 0)
                        dir_rows.append({
                            "Direction": label,
                            "Trades": len(group),
                            "Win%": f"{w/len(group)*100:.0f}%",
                            "Total P&L": f"${sum(e['pnl'] for e in group):+,.2f}",
                        })
                st.markdown('<div style="font-size:0.7rem;color:rgba(0,255,200,0.5);margin:12px 0 6px;letter-spacing:0.1em;">LONG VS SHORT</div>', unsafe_allow_html=True)
                st.dataframe(dir_rows, use_container_width=True, hide_index=True)

            # News categories that worked
            scan_evs = [e for e in all_events if e["type"] == "scan"]
            if scan_evs and all_exits:
                st.markdown('<div style="font-size:0.7rem;color:rgba(0,255,200,0.5);margin:12px 0 6px;letter-spacing:0.1em;">TICKERS TRADED</div>', unsafe_allow_html=True)
                ticker_rows = []
                tickers_traded = Counter(e["ticker"] for e in all_exits)
                for ticker, count in tickers_traded.most_common(8):
                    t_exits = [e for e in all_exits if e["ticker"] == ticker]
                    t_wins = sum(1 for e in t_exits if e["pnl"] > 0)
                    ticker_rows.append({
                        "Ticker": ticker,
                        "Trades": count,
                        "Win%": f"{t_wins/count*100:.0f}%",
                        "P&L": f"${sum(e['pnl'] for e in t_exits):+,.2f}",
                    })
                st.dataframe(ticker_rows, use_container_width=True, hide_index=True)

    if not events:
        st.markdown("""
        <div class="card" style="text-align:center;padding:40px;">
            <div style="font-family:Orbitron;font-size:1.1rem;color:rgba(0,255,200,0.5);letter-spacing:0.2em;">
                BOT OFFLINE
            </div>
            <div style="color:rgba(180,190,255,0.4);margin-top:12px;font-size:0.8rem;">
                Start the bot with: <code>uv run python run.py</code><br>
                Auto-starts at 08:00 ET on weekdays.
            </div>
        </div>
        """, unsafe_allow_html=True)

    if auto_refresh:
        _time.sleep(10)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_run:
    st.markdown('<div class="section-header">Test the strategy on a real recent day</div>', unsafe_allow_html=True)
    col_in, col_btn, col_demo = st.columns([2, 1, 1])
    ticker = col_in.text_input("Ticker", value="NVDA", label_visibility="collapsed",
                               placeholder="Ticker e.g. NVDA").strip().upper()
    run_real = col_btn.button("Run on real data", type="primary", use_container_width=True)
    run_demo = col_demo.button("Demo (synthetic)", use_container_width=True)

    CYAN, RED, BLUE = "#00ffc8", "#ff2d55", "#7c3aed"

    def price_chart(day_bars, result):
        s = result.state
        fig = go.Figure(go.Candlestick(
            x=day_bars.index,
            open=day_bars["open"], high=day_bars["high"],
            low=day_bars["low"], close=day_bars["close"],
            name="price", increasing_line_color=CYAN, decreasing_line_color=RED,
        ))
        if s.orh:
            fig.add_hline(y=s.orh, line_dash="dot", line_color=BLUE,
                          annotation_text="ORH")
        if s.orl:
            fig.add_hline(y=s.orl, line_dash="dot", line_color=BLUE,
                          annotation_text="ORL")
        for t in result.trades:
            up = t.direction.value == "long"
            fig.add_trace(go.Scatter(
                x=[t.entry_time], y=[float(t.entry_price)], mode="markers",
                marker=dict(symbol="triangle-up" if up else "triangle-down",
                            size=14, color=CYAN if up else RED),
                name=f"Entry S{t.strike_number}",
            ))
            fig.add_trace(go.Scatter(
                x=[t.exit_time], y=[float(t.exit_price)], mode="markers",
                marker=dict(symbol="x", size=12,
                            color=CYAN if t.realized_pnl() > 0 else RED),
                name=f"Exit S{t.strike_number}",
            ))
        fig.update_layout(
            height=480, margin=dict(t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(6,6,26,1)",
            xaxis=dict(showgrid=False, rangeslider_visible=False,
                       color="rgba(180,190,255,0.4)"),
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.04)",
                       color="rgba(180,190,255,0.4)"),
            legend=dict(orientation="h", y=-0.12,
                        font=dict(color="rgba(180,190,255,0.5)", size=11)),
        )
        return fig

    def show_result(result, day_bars):
        s = summary_stats(result)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Session P&L", f"${s['total_pnl']:,.2f}")
        c2.metric("Trades", s["trades"])
        c3.metric("Win rate", f"{s['win_rate']:.0f}%" if s["trades"] else "—")
        c4.metric("Strikes", f"{s['strikes']} / 3")
        if s["circuit_broken"]:
            st.error("Daily circuit breaker tripped — trading halted.")
        st.plotly_chart(price_chart(day_bars, result), use_container_width=True)
        if result.trades:
            rows = [{
                "Strike": t.strike_number,
                "Dir": "▲ Long" if t.direction.value == "long" else "▼ Short",
                "Entry": f"{float(t.entry_price):.3f}",
                "Exit": f"{float(t.exit_price):.3f}",
                "Reason": t.exit_reason.value.replace("_", " "),
                "P&L": f"${float(t.realized_pnl()):,.2f}",
                "In": t.entry_time.strftime("%H:%M"),
                "Out": t.exit_time.strftime("%H:%M"),
            } for t in result.trades]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No trades on this day.")

    if run_real:
        with st.spinner(f"Fetching {ticker} from yfinance..."):
            try:
                result, day_bars = load_and_run_yfinance(ticker)
                show_result(result, day_bars)
            except Exception as exc:
                st.error(f"Failed: {exc}")
    elif run_demo:
        with st.spinner("Generating synthetic session..."):
            stock_1m, qqq_1m = data.synthetic_session("2026-01-15", seed=42)
            result = run_backtest(stock_1m, qqq_1m, ticker="DEMO")
            day_bars = stock_1m[stock_1m.index.date == stock_1m.index[-1].date()]
            show_result(result, day_bars)


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_batch:
    st.markdown('<div class="section-header">Multi-ticker edge study</div>', unsafe_allow_html=True)
    st.caption("Runs the strategy over the last ~5 sessions across all tickers. "
               "Tiny sample — not a verdict, just a smoke test.")
    tickers_input = st.text_input("Tickers (comma-separated)", value="NVDA,TSLA,AMD,AAPL,META")
    run_batch_btn = st.button("Run batch", type="primary")
    if run_batch_btn:
        tickers_list = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
        with st.spinner("Running batch backtest..."):
            try:
                br = batch.run_batch(tickers_list)
                agg = batch.aggregate(br.sessions)
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("Sessions", agg["sessions_with_trades"])
                mc2.metric("Total trades", agg["trades"])
                mc3.metric("Win rate", f"{agg['win_rate']:.0f}%")
                mc4.metric("Expectancy", f"${agg['expectancy']:+.2f}/trade")
                mc5, mc6, mc7, mc8 = st.columns(4)
                mc5.metric("Total P&L", f"${agg['total_pnl']:+,.2f}")
                mc6.metric("Best trade", f"${agg['best']:+.2f}")
                mc7.metric("Worst trade", f"${agg['worst']:+.2f}")
                mc8.metric("Profit factor", f"{agg['profit_factor']:.2f}")
                if agg["trades"] > 1:
                    times, cum = batch.equity_curve(br.sessions)
                    lc = "#00ffc8" if cum[-1] >= 0 else "#ff2d55"
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=list(range(len(cum))), y=cum, mode="lines",
                        line=dict(color=lc, width=2),
                        fill="tozeroy",
                        fillcolor=f"{'rgba(0,255,200,0.06)' if cum[-1]>=0 else 'rgba(255,45,85,0.06)'}",
                    ))
                    fig.update_layout(
                        height=240, margin=dict(l=0, r=0, t=10, b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(6,6,26,1)",
                        xaxis=dict(showgrid=False, title="Trade #",
                                   color="rgba(180,190,255,0.4)"),
                        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.04)",
                                   tickprefix="$", color="rgba(180,190,255,0.4)"),
                        showlegend=False,
                    )
                    st.plotly_chart(fig, use_container_width=True)
                verdict = "POSITIVE EDGE" if agg["expectancy"] > 0 else "NEGATIVE EDGE"
                v_color = "#00ff88" if agg["expectancy"] > 0 else "#ff2d55"
                st.markdown(
                    f'<div class="card" style="text-align:center;">'
                    f'<div style="font-family:Orbitron;font-size:1.2rem;color:{v_color};letter-spacing:0.2em;">'
                    f'{verdict}</div>'
                    f'<div class="card-sub">on this small sample — need 200+ trades for a real verdict</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except Exception as exc:
                st.error(f"Batch failed: {exc}\n\nyfinance is often rate-limited — wait and retry.")


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS + SPEC TABS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_status:
    st.markdown(_read("ROADMAP.md"))

with tab_spec:
    left, right = st.columns(2)
    with left:
        st.subheader("Open questions")
        st.markdown(_read("docs/OPEN_QUESTIONS.md"))
    with right:
        st.subheader("Original strategy")
        st.markdown(_read("docs/STRATEGY_SPEC_ORIGINAL.md"))
