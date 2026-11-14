from datetime import date

import pytest

from donwoods_monitor.coverage import CoverageError, find_columns, parse_coverage, parse_list_date


def test_headers_found_by_name_not_position(cfg, fake_rows):
    names = parse_coverage(fake_rows, cfg)
    assert [n.ticker for n in names] == ["SU", "CCO", "TOU", "AAPL", "RCI.B", "ZZZ"]
    su = names[0]
    assert (su.sector, su.company, su.status, su.next_earnings_text) == ("E&U", "Suncor Energy", "Idea", "~Feb 2")
    assert su.listing.primary == "SU.TO"


def test_new_sector_picked_up(cfg, fake_rows):
    sectors = {n.sector for n in parse_coverage(fake_rows, cfg)}
    assert sectors == {"E&U", "TMT", "NEW"}


def test_bad_exchange_reported_not_dropped(cfg, fake_rows):
    z = [n for n in parse_coverage(fake_rows, cfg) if n.ticker == "ZZZ"][0]
    assert z.listing is None and "unknown exchange" in z.problems[0]


@pytest.mark.parametrize("missing", ["Sector", "Company", "Ticker", "Exchange"])
def test_missing_required_header_stops(cfg, fake_rows, missing):
    i = fake_rows[0].index(missing)
    fake_rows[0][i] = "Something else"
    with pytest.raises(CoverageError, match=missing):
        parse_coverage(fake_rows, cfg)


def test_header_case_and_spacing():
    cols = find_columns(["  sector ", "COMPANY", "Ticker", "exchange", "Next   earnings"],
                        ["Sector", "Company", "Ticker", "Exchange"], ["Next earnings", "Status"])
    assert cols == {"Sector": 0, "Company": 1, "Ticker": 2, "Exchange": 3, "Next earnings": 4}


def test_header_not_in_first_row(cfg, fake_rows):
    rows = [["Sector Coverage List"], [""]] + fake_rows
    assert len(parse_coverage(rows, cfg)) == 6


@pytest.mark.parametrize("text,expect,approx", [
    ("2026-12-03", date(2026, 12, 3), False),
    ("~Feb 2", date(2027, 2, 2), True),
    ("~Mid Feb", date(2027, 2, 15), True),
    ("~Early Mar", date(2027, 3, 5), True),
    ("~Late Jan", date(2027, 1, 25), True),
    ("~Nov 19", date(2026, 11, 19), True),
    ("~Dec 10", date(2026, 12, 10), True),
    ("", None, False),
    ("TBD", None, False),
])
def test_list_dates(text, expect, approx):
    d, a = parse_list_date(text, date(2026, 11, 14))
    assert d == expect
    if d:
        assert a == approx
