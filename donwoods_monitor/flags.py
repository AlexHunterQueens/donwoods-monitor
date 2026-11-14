"""Flag logic. Pure functions, no network, so it is easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .coverage import Name
from .edgar import Filing
from .prices import Metrics

BIG_MOVE = "Big move"
EARNINGS = "Earnings soon"
FILING = "New filing"
EXTREME = "52W extreme"
REPORT_OWED = "Report owed"

# Lower number sorts first on the Summary tab.
URGENCY = {REPORT_OWED: 0, BIG_MOVE: 1, FILING: 2, EARNINGS: 3, EXTREME: 4}


@dataclass
class Earnings:
    when: date | None
    source: str          # "yfinance", "list" or ""
    approx: bool = False
    text: str = ""       # original coverage list text

    @property
    def unconfirmed(self) -> bool:
        return self.source == "list"


@dataclass
class Flag:
    kind: str
    detail: str


@dataclass
class Result:
    name: Name
    metrics: Metrics | None = None
    earnings: Earnings | None = None
    filings: list[Filing] | None = None   # None means not checked on EDGAR
    filings_note: str = ""                # e.g. "check SEDAR+ manually"
    flags: list[Flag] = field(default_factory=list)

    @property
    def urgency(self) -> int:
        return min((URGENCY[f.kind] for f in self.flags), default=99)


def fmt_day(d: date) -> str:
    return f"{d:%b} {d.day}"


def earnings_text(e: Earnings) -> str:
    if e.when is None:
        return e.text or ""
    if e.unconfirmed:
        # Keep the team's own wording ("Feb 2", "Early Mar") so nothing looks more precise than it is.
        shown = e.text.lstrip("~ ") if e.approx and e.text else fmt_day(e.when)
        return f"{shown} (from list, unconfirmed)"
    return fmt_day(e.when)


def days_to(e: Earnings | None, today: date) -> int | None:
    if not e or e.when is None:
        return None
    return (e.when - today).days


def evaluate(r: Result, today: date, cfg: dict, bench_name: str = "TSX") -> list[Flag]:
    fc = cfg["flags"]
    flags: list[Flag] = []
    m = r.metrics

    if m and m.w1_pct is not None:
        big_abs = abs(m.w1_pct) >= fc["big_move"]["weekly_pct"]
        big_rel = m.w1_vs_bench_pp is not None and abs(m.w1_vs_bench_pp) >= fc["big_move"]["vs_benchmark_pp"]
        if big_abs or big_rel:
            detail = f"{'up' if m.w1_pct >= 0 else 'down'} {abs(m.w1_pct):.1f}% on the week"
            if m.w1_vs_bench_pp is not None:
                side = "above" if m.w1_vs_bench_pp >= 0 else "below"
                detail += f", {abs(m.w1_vs_bench_pp):.1f} pp {side} the {bench_name}"
            flags.append(Flag(BIG_MOVE, detail))

    if r.filings:
        parts = ", ".join(f"{f.form} {fmt_day(f.filed)}" for f in r.filings)
        flags.append(Flag(FILING, f"new filing: {parts}"))

    d = days_to(r.earnings, today)
    if d is not None and 0 <= d <= fc["earnings_soon"]["days"]:
        flags.append(Flag(EARNINGS, f"earnings {earnings_text(r.earnings)}"))

    if m:
        within = fc["extreme_52w"]["within_pct"]
        if m.high_52w and m.last_price >= m.high_52w * (1 - within / 100):
            flags.append(Flag(EXTREME, f"{abs(m.pct_from_high):.1f}% below 52W high"
                              if m.pct_from_high < -0.05 else "at 52W high"))
        elif m.low_52w and m.last_price <= m.low_52w * (1 + within / 100):
            flags.append(Flag(EXTREME, f"{m.pct_from_low:.1f}% above 52W low"
                              if m.pct_from_low > 0.05 else "at 52W low"))

    ro = fc["report_owed"]
    statuses = {s.casefold() for s in ro["statuses"]}
    if r.name.status.casefold() in statuses:
        hit = [f.kind for f in flags if f.kind in ro["triggers"]]
        if hit:
            flags.append(Flag(REPORT_OWED, f"report in progress, draft may need updating after "
                              f"{' and '.join(h.lower() for h in hit)}"))

    flags.sort(key=lambda f: URGENCY[f.kind])
    return flags
