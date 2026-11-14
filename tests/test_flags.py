from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from donwoods_monitor import monitor as M
from donwoods_monitor.coverage import Name, parse_coverage
from donwoods_monitor.edgar import Filing, filter_filings
from donwoods_monitor.flags import (BIG_MOVE, EARNINGS, EXTREME, FILING, REPORT_OWED, Earnings,
                                    Result, evaluate)
from donwoods_monitor.prices import Metrics, compute_metrics
from donwoods_monitor.tickers import map_listing

TODAY = date(2026, 11, 14)  # Saturday


def metrics(w1=0.0, vs=0.0, last=100.0, hi=150.0, lo=50.0):
    return Metrics(asof=date(2026, 11, 13), last_price=last, w1_pct=w1, w1_vs_bench_pp=vs, m1_pct=0.0,
                   high_52w=hi, low_52w=lo, pct_from_high=(last / hi - 1) * 100,
                   pct_from_low=(last / lo - 1) * 100)


def result(status="Idea", **kw):
    n = Name(sector="E&U", company="Suncor", ticker="SU", exchange="TSX / NYSE", status=status,
             listing=map_listing("SU", "TSX / NYSE"))
    return Result(name=n, **kw)


def kinds(flags):
    return [f.kind for f in flags]


@pytest.mark.parametrize("w1,vs,flag", [
    (5.0, 1.0, True), (-5.0, -1.0, True), (4.9, 2.9, False),
    (1.0, 3.0, True), (-1.0, -3.0, True), (2.0, -2.9, False),
])
def test_big_move_thresholds(cfg, w1, vs, flag):
    assert (BIG_MOVE in kinds(evaluate(result(metrics=metrics(w1, vs)), TODAY, cfg))) is flag


def test_big_move_wording(cfg):
    f = evaluate(result(metrics=metrics(-6.2, -4.1)), TODAY, cfg)[0]
    assert f.detail == "down 6.2% on the week, 4.1 pp below the TSX"
    assert "—" not in f.detail and " - " not in f.detail


@pytest.mark.parametrize("days,flag", [(0, True), (14, True), (15, False), (-1, False)])
def test_earnings_window(cfg, days, flag):
    e = Earnings(TODAY + timedelta(days=days), "yfinance")
    assert (EARNINGS in kinds(evaluate(result(earnings=e), TODAY, cfg))) is flag


def test_earnings_from_list_marked_unconfirmed(cfg):
    e = Earnings(date(2026, 11, 19), "list", True, "~Nov 19")
    f = [x for x in evaluate(result(earnings=e), TODAY, cfg) if x.kind == EARNINGS][0]
    assert f.detail == "earnings Nov 19 (from list, unconfirmed)"


def test_new_filing(cfg):
    r = result(filings=[Filing("6-K", date(2026, 11, 12), "u")])
    f = [x for x in evaluate(r, TODAY, cfg) if x.kind == FILING][0]
    assert f.detail == "new filing: 6-K Nov 12"
    assert FILING not in kinds(evaluate(result(filings=[]), TODAY, cfg))


@pytest.mark.parametrize("last,hi,lo,flag", [
    (98.5, 100.0, 50.0, True),    # 1.5% below high
    (97.9, 100.0, 50.0, False),   # 2.1% below high
    (51.0, 100.0, 50.0, True),    # 2% above low
    (51.1, 100.0, 50.0, False),
])
def test_52w_extreme(cfg, last, hi, lo, flag):
    r = result(metrics=metrics(last=last, hi=hi, lo=lo))
    assert (EXTREME in kinds(evaluate(r, TODAY, cfg))) is flag


def test_report_owed_needs_in_progress_and_trigger(cfg):
    assert REPORT_OWED in kinds(evaluate(result("In progress", metrics=metrics(6, 6)), TODAY, cfg))
    assert REPORT_OWED in kinds(evaluate(
        result("in progress", filings=[Filing("8-K", TODAY, "u")]), TODAY, cfg))
    assert REPORT_OWED not in kinds(evaluate(result("Idea", metrics=metrics(6, 6)), TODAY, cfg))
    # Earnings alone does not trigger it
    e = Earnings(TODAY + timedelta(days=3), "yfinance")
    assert REPORT_OWED not in kinds(evaluate(result("In progress", earnings=e), TODAY, cfg))


def test_report_owed_sorts_first(cfg):
    flags = evaluate(result("In progress", metrics=metrics(8, 8, last=149, hi=150)), TODAY, cfg)
    assert kinds(flags) == [REPORT_OWED, BIG_MOVE, EXTREME]


def test_thresholds_come_from_config(cfg):
    cfg["flags"]["big_move"]["weekly_pct"] = 10
    cfg["flags"]["big_move"]["vs_benchmark_pp"] = 10
    assert BIG_MOVE not in kinds(evaluate(result(metrics=metrics(6, 6)), TODAY, cfg))


# ---------- prices ----------

def frame(closes, end="2026-11-13"):
    idx = pd.bdate_range(end=end, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99})


def test_compute_metrics_week_vs_bench():
    stock = frame([100.0] * 300 + [100, 100, 100, 100, 100, 94])   # last Fri 94, prior Fri 100
    bench = frame([1000.0] * 300 + [1000, 1000, 1000, 1000, 1000, 980])
    m = compute_metrics(stock, bench)
    assert m.asof == date(2026, 11, 13)
    assert m.w1_pct == pytest.approx(-6.0)
    assert m.w1_vs_bench_pp == pytest.approx(-4.0)
    assert m.high_52w == pytest.approx(101.0)


def test_compute_metrics_empty():
    assert compute_metrics(frame([]), None) is None


# ---------- EDGAR ----------

def test_filter_filings():
    data = {"filings": {"recent": {
        "form": ["8-K", "4", "10-Q/A", "40-F", "8-K"],
        "filingDate": ["2026-11-13", "2026-11-13", "2026-11-10", "2026-11-07", "2026-11-01"],
        "accessionNumber": ["0001-26-1", "0001-26-2", "0001-26-3", "0001-26-4", "0001-26-5"],
        "primaryDocument": ["a.htm", "b.xml", "c.htm", "d.htm", "e.htm"],
    }}}
    got = filter_filings(data, 123, TODAY, 7, ["8-K", "10-Q", "40-F"], True)
    assert [f.form for f in got] == ["8-K", "10-Q/A"]   # Form 4 ignored, Nov 7 and Nov 1 too old
    assert got[0].url.endswith("/123/0001261/a.htm")
    assert [f.form for f in filter_filings(data, 1, TODAY, 7, ["10-Q"], False)] == []


# ---------- whole run on the fake list ----------

class FakeEdgar:
    def cik_for(self, t):
        return {"SU": 1, "CCJ": 2, "AAPL": 3}.get(t)

    def recent_filings(self, cik, today, lookback, forms, amend):
        return [Filing("6-K", date(2026, 11, 12), "u")] if cik == 2 else []


def test_build_run_end_to_end(cfg, fake_rows):
    names = parse_coverage(fake_rows, cfg)
    flat = frame([100.0] * 306)
    hist = {
        "^GSPTSE": frame([1000.0] * 305 + [1020]),
        "SU.TO": frame([100.0] * 305 + [94]),
        "CCO.TO": frame([100.0] * 306),
        "AAPL": flat,
        # TOU.TO and RCI-B.TO missing: must show up as data problems
    }
    run = M.build_run(
        names, cfg, TODAY, datetime(2026, 11, 14, 8, 0),
        fetch_history=lambda syms: {s: hist[s] for s in syms if s in hist},
        fetch_earnings=lambda sym, today: date(2026, 11, 20) if sym == "AAPL" else None,
        edgar=FakeEdgar())

    assert len(run.results) == 6 and run.priced == 3
    assert run.sectors == ["E&U", "TMT", "NEW"]
    probs = " ".join(p[3] for p in run.problems)
    assert "TOU.TO" in probs and "RCI-B.TO" in probs and "unknown exchange" in probs
    assert "no SEC CIK for RCI" in probs

    by = {r.name.ticker: r for r in run.results}
    assert kinds(by["SU"].flags) == [BIG_MOVE, EXTREME]   # 94 is also a new 52W low
    assert by["SU"].flags[0].detail == "down 6.0% on the week, 8.0 pp below the TSX"
    assert kinds(by["CCO"].flags)[:2] == [REPORT_OWED, FILING]     # In progress plus a 6-K
    assert by["TOU"].filings_note == "check SEDAR+ manually"
    assert EARNINGS in kinds(by["AAPL"].flags)                      # yfinance date, 6 days out

    rows = M.sector_rows(run, "E&U")
    assert len(rows) == 3 and len(rows[0]) == len(M.SECTOR_HEADERS)
    assert rows[2][12] == "check SEDAR+ manually"

    summ = M.summary_rows(run)
    assert [r[2] for r in summ][:2] == ["CCO", "SU"]   # E&U first, Report owed outranks Big move

    digest = "\n".join(M.digest_lines(run))
    assert "SU down 6.0% on the week, 8.0 pp below the TSX" in digest
    assert "—" not in digest and " - " not in digest
    assert "Data problems" in digest
