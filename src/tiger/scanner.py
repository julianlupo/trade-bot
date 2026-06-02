"""
Pre-market gap + news scanner.
Runs at ~08:00 ET, returns top ticker candidates for the day.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.historical import NewsClient, StockHistoricalDataClient
from alpaca.data.requests import NewsRequest, StockSnapshotRequest
from dotenv import load_dotenv

ET = ZoneInfo("America/New_York")

# Liquid universe — covers most intraday momentum movers
UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "AMD", "AVGO", "ORCL", "CRM", "ADBE", "QCOM", "INTC",
    # High-momentum names
    "SMCI", "ARM", "PLTR", "MSTR", "COIN", "HOOD", "RBLX",
    "SOFI", "UPST", "AFRM", "SNAP", "UBER", "LYFT",
    # Biotech / pharma (frequent gap-on-news)
    "MRNA", "BNTX", "BIIB", "VRTX", "REGN", "GILD", "LLY",
    "ABBV", "PFE", "BMY",
    # Energy
    "XOM", "CVX", "OXY",
    # Financials
    "JPM", "BAC", "GS", "MS", "C",
    # Consumer
    "NKE", "SBUX", "MCD", "CMG", "LULU",
    # Industrials / defense
    "BA", "RTX", "LMT", "GE", "CAT",
]

MIN_GAP_PCT = 0.04   # 4% minimum gap to qualify
MAX_CANDIDATES = 3   # how many tickers to hand to the live engine


@dataclass
class Candidate:
    ticker: str
    gap_pct: float
    direction: str          # "long" or "short"
    prev_close: float
    premarket_price: float
    headlines: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        sign = "+" if self.gap_pct > 0 else ""
        heds = (" | " + self.headlines[0][:70]) if self.headlines else ""
        return (
            f"{self.ticker:6s}  gap={sign}{self.gap_pct:.1%}  "
            f"prev={self.prev_close:.2f}  pm={self.premarket_price:.2f}"
            f"  [{self.direction.upper()}]{heds}"
        )


def _clients() -> tuple[StockHistoricalDataClient, NewsClient]:
    load_dotenv()
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    return (
        StockHistoricalDataClient(api_key=key, secret_key=secret),
        NewsClient(api_key=key, secret_key=secret),
    )


def _get_snapshots(tickers: list[str]) -> dict:
    data_client, _ = _clients()
    return data_client.get_stock_snapshot(
        StockSnapshotRequest(symbol_or_symbols=tickers)
    )


def _get_news(tickers: list[str], hours_back: int = 18) -> dict[str, list[str]]:
    """Returns {ticker: [headline, ...]} for news published in the last hours_back hours."""
    _, news_client = _clients()
    since = datetime.now(ET) - timedelta(hours=hours_back)
    symbols_str = ",".join(tickers)
    result = news_client.get_news(
        NewsRequest(symbols=symbols_str, start=since, limit=100)
    )
    by_ticker: dict[str, list[str]] = {}
    for article in result.data.get("news", []):
        for sym in article.symbols:
            if sym in tickers:
                by_ticker.setdefault(sym, []).append(article.headline)
    return by_ticker


def find_candidates(
    universe: list[str] = UNIVERSE,
    min_gap_pct: float = MIN_GAP_PCT,
    max_results: int = MAX_CANDIDATES,
) -> list[Candidate]:
    """
    Scan universe for pre-market gaps with a news catalyst.
    Returns up to max_results candidates, sorted by abs(gap_pct) desc.
    """
    snapshots = _get_snapshots(universe)

    gappers: list[Candidate] = []
    for ticker, snap in snapshots.items():
        try:
            prev_close = float(snap.daily_bar.close) if snap.daily_bar else None
            pm_price = float(snap.latest_trade.price) if snap.latest_trade else None
            if not prev_close or not pm_price:
                continue
            gap = (pm_price - prev_close) / prev_close
            if abs(gap) < min_gap_pct:
                continue
            gappers.append(Candidate(
                ticker=ticker,
                gap_pct=gap,
                direction="long" if gap > 0 else "short",
                prev_close=prev_close,
                premarket_price=pm_price,
            ))
        except Exception:
            continue

    gappers.sort(key=lambda c: abs(c.gap_pct), reverse=True)

    # Fetch news only for top candidates to keep it fast
    top_n = gappers[: max_results * 4]
    if not top_n:
        return []

    news_map = _get_news([c.ticker for c in top_n])
    for c in top_n:
        c.headlines = news_map.get(c.ticker, [])

    # Prefer candidates with news; fall back to pure gap size if none have news
    with_news = [c for c in top_n if c.headlines]
    ranked = with_news if with_news else top_n
    return ranked[:max_results]


def run_scan(print_results: bool = True) -> list[Candidate]:
    now = datetime.now(ET)
    print(f"[scanner] {now.strftime('%Y-%m-%d %H:%M ET')} — scanning {len(UNIVERSE)} tickers...")
    candidates = find_candidates()

    if print_results:
        if not candidates:
            print("[scanner] No gap candidates with news catalyst found today.")
        else:
            print(f"[scanner] {len(candidates)} candidate(s):\n")
            for c in candidates:
                print(f"  {c}")
    return candidates


if __name__ == "__main__":
    run_scan()
