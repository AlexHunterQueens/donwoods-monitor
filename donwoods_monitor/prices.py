"""Prices and earnings dates from Yahoo Finance via yfinance."""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class Metrics:
    asof: date
    last_price: float
    w1_pct: float | None
    w1_vs_bench_pp: float | None
    m1_pct: float | None
    high_52w: float
    low_52w: float
    pct_from_high: float
    pct_from_low: float


def _close_on_or_before(s: pd.Series, d: date) -> float | None:
    s = s.dropna()
    s = s[s.index.date <= d]
    return float(s.iloc[-1]) if len(s) else None


def compute_metrics(hist: pd.DataFrame, bench: pd.DataFrame | None) -> Metrics | None:
    """hist and bench have a DatetimeIndex and Close, High, Low columns.
    1W: last close vs last close on or before 7 calendar days earlier.
    1M: same, one calendar month earlier.
    52W high and low: daily highs and lows over the last 365 days (matches Yahoo's range)."""
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        return None
    asof = hist.index[-1].date()
    last = float(hist["Close"].iloc[-1])

    def ret(series, start, end):
        a, b = _close_on_or_before(series, start), _close_on_or_before(series, end)
        return None if a in (None, 0) or b is None else (b / a - 1) * 100

    w_start = asof - timedelta(days=7)
    m_start = (pd.Timestamp(asof) - pd.DateOffset(months=1)).date()
    w1 = ret(hist["Close"], w_start, asof)
    m1 = ret(hist["Close"], m_start, asof)
    vs = None
    if bench is not None and not bench.empty and w1 is not None:
        b = ret(bench["Close"], w_start, asof)
        vs = None if b is None else w1 - b

    yr = hist[hist.index.date > asof - timedelta(days=365)]
    hi = float(yr["High"].max()) if "High" in yr else float(yr["Close"].max())
    lo = float(yr["Low"].min()) if "Low" in yr else float(yr["Close"].min())
    hi, lo = max(hi, last), min(lo, last)
    return Metrics(
        asof=asof, last_price=last, w1_pct=w1, w1_vs_bench_pp=vs, m1_pct=m1,
        high_52w=hi, low_52w=lo,
        pct_from_high=(last / hi - 1) * 100 if hi else 0.0,
        pct_from_low=(last / lo - 1) * 100 if lo else 0.0,
    )


def _yf():
    import yfinance as yf
    # yfinance keeps a timezone cache in sqlite that locks under load; give it a private dir.
    yf.set_tz_cache_location(tempfile.mkdtemp(prefix="yf-tz-"))
    return yf


def fetch_history(symbols: list[str], retries: int = 3) -> dict[str, pd.DataFrame]:
    """Daily OHLC for about 13 months. Unadjusted closes, so numbers match Yahoo's quote page."""
    yf = _yf()
    out: dict[str, pd.DataFrame] = {}
    todo = sorted(set(symbols))
    for attempt in range(retries):
        if not todo:
            break
        try:
            df = yf.download(todo, period="13mo", interval="1d", auto_adjust=False,
                             group_by="ticker", threads=False, progress=False)
        except Exception as e:  # network or rate limit
            log.warning("yfinance download failed (attempt %d): %s", attempt + 1, e)
            df = pd.DataFrame()
        for sym in list(todo):
            try:
                sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
                sub = sub[["Close", "High", "Low"]].dropna(subset=["Close"])
            except (KeyError, TypeError):
                continue
            if not sub.empty:
                out[sym] = sub
                todo.remove(sym)
        if todo:
            time.sleep(5 * (attempt + 1))
    return out


def fetch_earnings_date(symbol: str, today: date) -> date | None:
    """Next earnings date from yfinance, or None if it has none in the future."""
    yf = _yf()
    try:
        cal = yf.Ticker(symbol).calendar
    except Exception as e:
        log.info("no calendar for %s: %s", symbol, e)
        return None
    dates = []
    if isinstance(cal, dict):
        dates = cal.get("Earnings Date") or []
    elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
        dates = list(cal.loc["Earnings Date"].values)
    if not isinstance(dates, (list, tuple)):
        dates = [dates]
    clean = []
    for d in dates:
        try:
            clean.append(pd.Timestamp(d).date())
        except Exception:
            pass
    future = sorted(d for d in clean if d >= today)
    return future[0] if future else None
