"""Build results for every covered name, then the tables and digest."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd

from .coverage import Name, parse_list_date
from .flags import Earnings, Result, days_to, earnings_text, evaluate, fmt_day

log = logging.getLogger(__name__)

SECTOR_MARKER = "Coverage Monitor sector tab"
SECTOR_HEADERS = ["Company", "Ticker", "Status", "Last price", "1W %", "1W vs TSX (pp)", "1M %",
                  "52W high", "52W low", "% from 52W high", "Next earnings", "Days to earnings",
                  "New filings (7d)", "Flags", "Yahoo symbol"]
SUMMARY_HEADERS = ["Sector", "Company", "Ticker", "Flag", "Detail", "Analysts"]
PROBLEM_HEADERS = ["Sector", "Company", "Ticker", "Problem"]
DROPPED_HEADERS = ["Date dropped", "Last sector", "Company", "Ticker"]
RUNLOG_HEADERS = ["Timestamp (Toronto)", "Mode", "Names read", "Names priced", "Flags raised",
                  "Names flagged", "Data problems", "Problem tickers", "Prices as of"]


@dataclass
class Run:
    today: date
    run_at: datetime
    results: list[Result]
    asof: date | None
    sectors: list[str]
    bench_symbol: str
    bench_name: str
    edgar_ok: bool
    lookback_days: int
    problems: list[tuple[str, str, str, str]] = field(default_factory=list)

    @property
    def priced(self) -> int:
        return sum(1 for r in self.results if r.metrics)

    @property
    def flagged(self) -> list[Result]:
        return [r for r in self.results if r.flags]


def build_run(names: list[Name], cfg: dict, today: date, run_at: datetime, *,
              fetch_history: Callable, fetch_earnings: Callable, edgar=None,
              edgar_error: str = "") -> Run:
    from .prices import compute_metrics

    bench_sym = cfg["benchmark"]["ticker"]
    bench_name = cfg["benchmark"].get("name", "TSX")
    lookback = cfg["flags"]["new_filing"]["lookback_days"]

    sectors: list[str] = []
    for n in names:
        if n.sector and n.sector not in sectors:
            sectors.append(n.sector)

    symbols = [n.listing.primary for n in names if n.listing]
    hist = fetch_history(symbols + [bench_sym]) if symbols else {}
    bench = hist.get(bench_sym)

    problems: list[tuple[str, str, str, str]] = []
    if bench is None:
        problems.append(("", cfg["benchmark"].get("name", ""), bench_sym,
                         "no benchmark data, 1W vs TSX left blank"))
    asof = bench.index[-1].date() if bench is not None else None

    results: list[Result] = []
    for n in names:
        r = Result(name=n)
        for p in n.problems:
            problems.append((n.sector, n.company, n.ticker, p))
        if n.listing:
            h = hist.get(n.listing.primary)
            r.metrics = compute_metrics(h, bench) if h is not None else None
            if r.metrics is None:
                problems.append((n.sector, n.company, n.ticker,
                                 f"no price data from Yahoo for {n.listing.primary}"))

            when = fetch_earnings(n.listing.primary, today)
            if when:
                r.earnings = Earnings(when, "yfinance")
            else:
                d, approx = parse_list_date(n.next_earnings_text, today)
                r.earnings = Earnings(d, "list" if d else "", approx, n.next_earnings_text)

            if n.listing.us_ticker is None:
                r.filings_note = "check SEDAR+ manually"
            elif edgar is None:
                r.filings_note = "EDGAR not checked"
            else:
                try:
                    cik = edgar.cik_for(n.listing.us_ticker)
                    if cik is None:
                        r.filings_note = "not found on EDGAR, check SEDAR+ manually"
                        problems.append((n.sector, n.company, n.ticker,
                                         f"no SEC CIK for {n.listing.us_ticker}"))
                    else:
                        r.filings = edgar.recent_filings(
                            cik, today, lookback, cfg["flags"]["new_filing"]["forms"],
                            cfg["flags"]["new_filing"].get("include_amendments", True))
                except Exception as e:  # keep going, report it
                    r.filings_note = "EDGAR error"
                    problems.append((n.sector, n.company, n.ticker, f"EDGAR lookup failed: {e}"))
        r.flags = evaluate(r, today, cfg, bench_name)
        results.append(r)

    if asof is None:
        dates = [r.metrics.asof for r in results if r.metrics]
        asof = max(dates) if dates else None
    if asof:
        for r in results:
            if r.metrics and r.metrics.asof < asof - timedelta(days=4):
                problems.append((r.name.sector, r.name.company, r.name.ticker,
                                 f"stale price, last close {r.metrics.asof.isoformat()}"))
    if edgar is None and edgar_error:
        problems.append(("", "", "", f"EDGAR skipped: {edgar_error}"))

    return Run(today=today, run_at=run_at, results=results, asof=asof, sectors=sectors,
               bench_symbol=bench_sym, bench_name=bench_name, edgar_ok=edgar is not None,
               lookback_days=lookback, problems=problems)


# ---------- formatting ----------

def _r(x, nd):
    return "" if x is None else round(float(x), nd)


def source_line(run: Run, marker: str = "") -> str:
    asof = f"close {run.asof:%a %b} {run.asof.day} {run.asof:%Y}" if run.asof else "no price data"
    since = run.today - timedelta(days=run.lookback_days)
    parts = [p for p in [
        marker,
        f"Prices: Yahoo Finance via yfinance, {asof}, unadjusted, listing currency (CAD for TSX, USD for US)",
        f"Benchmark: S&P/TSX Composite ({run.bench_symbol}) over the same week",
        "Earnings: yfinance, falls back to coverage list (marked unconfirmed)",
        (f"Filings: SEC EDGAR, {fmt_day(since)} to {fmt_day(run.today)} {run.today:%Y}"
         if run.edgar_ok else "Filings: EDGAR not checked this run"),
        f"Run {run.run_at:%a %b} {run.run_at.day} {run.run_at:%Y %H:%M} Toronto",
    ] if p]
    return " | ".join(parts)


def filings_cell(r: Result) -> str:
    if r.filings:
        return ", ".join(f"{f.form} {fmt_day(f.filed)}" for f in r.filings)
    if r.filings is not None:
        return "none"
    return r.filings_note


def sector_rows(run: Run, sector: str) -> list[list]:
    rows = []
    for r in run.results:
        if r.name.sector != sector:
            continue
        m = r.metrics
        rows.append([
            r.name.company, r.name.ticker, r.name.status,
            _r(m and m.last_price, 2), _r(m and m.w1_pct, 1), _r(m and m.w1_vs_bench_pp, 1),
            _r(m and m.m1_pct, 1), _r(m and m.high_52w, 2), _r(m and m.low_52w, 2),
            _r(m and m.pct_from_high, 1),
            earnings_text(r.earnings) if r.earnings else "",
            "" if (d := days_to(r.earnings, run.today)) is None or d < 0 else d,
            filings_cell(r),
            "; ".join(f.kind for f in r.flags),
            r.name.listing.primary if r.name.listing else "",
        ])
    return rows


def summary_rows(run: Run) -> list[list]:
    order = {s: i for i, s in enumerate(run.sectors)}
    flagged = sorted(run.flagged, key=lambda r: (order.get(r.name.sector, 99), r.urgency))
    return [[r.name.sector, r.name.company, r.name.ticker,
             "; ".join(f.kind for f in r.flags),
             "; ".join(f.detail for f in r.flags),
             r.name.analysts] for r in flagged]


def digest_lines(run: Run) -> list[str]:
    head = (f"Coverage Monitor, week to {run.asof:%a %b} {run.asof.day} {run.asof:%Y}"
            if run.asof else "Coverage Monitor")
    lines = [head, "Names on our list that moved. The why is yours to add.", ""]
    for s in run.sectors:
        lines.append(s)
        hits = [r for r in run.flagged if r.name.sector == s]
        hits.sort(key=lambda r: r.urgency)
        if not hits:
            lines.append("No names flagged.")
        for r in hits:
            lines.append(f"{r.name.ticker} " + "; ".join(f.detail for f in r.flags))
        lines.append("")
    if run.problems:
        lines.append("Data problems")
        for sec, comp, tick, prob in run.problems:
            who = " ".join(x for x in [tick, f"({comp})" if comp else ""] if x)
            lines.append(f"{who}: {prob}" if who else prob)
    return lines


def runlog_row(run: Run, mode: str) -> list:
    flags = sum(len(r.flags) for r in run.results)
    bad = sorted({p[2] for p in run.problems if p[2]})
    return [run.run_at.strftime("%Y-%m-%d %H:%M"), mode, len(run.results), run.priced, flags,
            len(run.flagged), len(run.problems), ", ".join(bad),
            run.asof.isoformat() if run.asof else ""]


def as_frame(headers: list[str], rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=headers)
