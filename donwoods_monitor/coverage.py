"""Read the coverage list. Header lookup by name, never by position."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .tickers import Listing, MappingError, map_listing


class CoverageError(RuntimeError):
    pass


@dataclass
class Name:
    sector: str
    company: str
    ticker: str
    exchange: str
    analysts: str = ""
    status: str = ""
    next_earnings_text: str = ""
    listing: Listing | None = None
    problems: list[str] = field(default_factory=list)


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip()).casefold()


def find_columns(header: list[str], required: list[str], optional: list[str]) -> dict[str, int]:
    """Map wanted header names to column indexes. Missing required headers raise."""
    index = {}
    for i, h in enumerate(header):
        index.setdefault(_norm(h), i)
    missing = [r for r in required if _norm(r) not in index]
    if missing:
        raise CoverageError("Coverage list is missing required header(s): " + ", ".join(missing))
    cols = {r: index[_norm(r)] for r in required}
    for o in optional:
        if _norm(o) in index:
            cols[o] = index[_norm(o)]
    return cols


def _find_header_row(rows: list[list[str]], required: list[str]) -> int:
    """Header is the first of the top 10 rows that holds every required name.
    If none does, use the row with the most matches so the error names what is missing."""
    want = {_norm(r) for r in required}
    best, best_hits = 0, -1
    for i, row in enumerate(rows[:10]):
        hits = len(want & {_norm(c) for c in row})
        if hits == len(want):
            return i
        if hits > best_hits:
            best, best_hits = i, hits
    return best


def parse_coverage(rows: list[list[str]], cfg: dict) -> list[Name]:
    if not rows:
        raise CoverageError("Coverage list is empty")
    required = cfg["columns"]["required"]
    optional = cfg["columns"].get("optional", [])
    h = _find_header_row(rows, required)
    cols = find_columns(rows[h], required, optional)

    def cell(row, key):
        i = cols.get(key)
        return row[i].strip() if i is not None and i < len(row) and row[i] else ""

    names: list[Name] = []
    for row in rows[h + 1:]:
        sector, company, ticker = cell(row, "Sector"), cell(row, "Company"), cell(row, "Ticker")
        if not (sector or company or ticker):
            continue  # blank row
        n = Name(
            sector=sector, company=company, ticker=ticker.upper(),
            exchange=cell(row, "Exchange"), analysts=cell(row, "Analysts"),
            status=cell(row, "Status"), next_earnings_text=cell(row, "Next earnings"),
        )
        if not sector:
            n.problems.append("no sector in coverage list")
        if not ticker:
            n.problems.append("no ticker in coverage list")
        else:
            try:
                n.listing = map_listing(ticker, n.exchange, cfg.get("ticker_overrides"))
            except MappingError as e:
                n.problems.append(f"ticker mapping failed: {e}")
        names.append(n)
    return names


# Next earnings column, e.g. "2026-12-03", "~Feb 2", "~Mid Feb", "~Early Mar"
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_PART_DAY = {"early": 5, "mid": 15, "late": 25}


def parse_list_date(text: str, today: date) -> tuple[date | None, bool]:
    """Return (date, approximate). Month only dates roll to the next occurrence."""
    t = (text or "").strip()
    if not t:
        return None, False
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])), False
        except ValueError:
            return None, False
    approx = t.startswith("~")
    t = t.lstrip("~ ").lower()
    m = re.fullmatch(r"(early|mid|late)\s+([a-z]{3})[a-z]*", t)
    if m:
        month, day = _MONTHS.get(m[2]), _PART_DAY[m[1]]
        approx = True
    else:
        m = re.fullmatch(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})", t)
        if not m:
            return None, False
        month, day = _MONTHS.get(m[1]), int(m[2])
    if not month:
        return None, False
    year = today.year
    try:
        d = date(year, month, day)
        if (today - d).days > 60:  # "~Feb 2" read in November means next February
            d = date(year + 1, month, day)
    except ValueError:
        return None, False
    return d, approx
