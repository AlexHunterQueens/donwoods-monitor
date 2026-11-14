import pytest

from donwoods_monitor.tickers import MappingError, map_listing


@pytest.mark.parametrize("ticker,exch,primary,us,ccy", [
    ("SU", "TSX / NYSE", "SU.TO", "SU", "CAD"),
    ("TOU", "TSX", "TOU.TO", None, "CAD"),
    ("CCO", "TSX / NYSE (CCJ)", "CCO.TO", "CCJ", "CAD"),
    ("RCI.B", "TSX / NYSE (RCI)", "RCI-B.TO", "RCI", "CAD"),
    ("SHOP", "TSX / NASDAQ", "SHOP.TO", "SHOP", "CAD"),
    ("XOM", "NYSE", "XOM", "XOM", "USD"),
    ("AAPL", "NASDAQ", "AAPL", "AAPL", "USD"),
    ("aapl", " nasdaq ", "AAPL", "AAPL", "USD"),
    ("BRK.B", "NYSE", "BRK-B", "BRK.B", "USD"),
])
def test_mapping(ticker, exch, primary, us, ccy):
    m = map_listing(ticker, exch)
    assert (m.primary, m.us_ticker, m.currency) == (primary, us, ccy)


def test_override_wins():
    m = map_listing("L", "TSX", {"L": {"primary": "L.TO", "us": ""}})
    assert m.primary == "L.TO" and m.us_ticker is None


def test_override_rescues_unknown_exchange():
    m = map_listing("ZZZ", "LSE", {"ZZZ": {"primary": "ZZZ.L", "currency": "GBP"}})
    assert m.primary == "ZZZ.L" and m.currency == "GBP"


@pytest.mark.parametrize("ticker,exch", [("ZZZ", "LSE"), ("", "TSX"), ("ABC", "")])
def test_bad_inputs_raise(ticker, exch):
    with pytest.raises(MappingError):
        map_listing(ticker, exch)
