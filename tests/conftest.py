import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from donwoods_monitor.config import load_config  # noqa: E402


@pytest.fixture
def cfg():
    return load_config(Path(__file__).resolve().parent.parent / "config.yaml")


# Fake coverage list: reordered columns, an extra column, a blank row, odd exchanges.
FAKE_ROWS = [
    ["Notes", "Ticker", "Company", "#", "Exchange", "Sector", "Status", "Analysts", "Next earnings"],
    ["", "SU", "Suncor Energy", "1", "TSX / NYSE", "E&U", "Idea", "A One, B Two", "~Feb 2"],
    ["", "CCO", "Cameco", "2", "TSX / NYSE (CCJ)", "E&U", "In progress", "A One, B Two", "~Mid Feb"],
    ["", "TOU", "Tourmaline Oil", "3", "TSX", "E&U", "Idea", "A One, B Two", ""],
    ["", "", "", "", "", "", "", "", ""],
    ["", "AAPL", "Apple", "4", "NASDAQ", "TMT", "In progress", "C Three, D Four", "2026-11-20"],
    ["", "RCI.B", "Rogers", "5", "TSX / NYSE (RCI)", "TMT", "Idea", "C Three, D Four", "~Late Jan"],
    ["", "ZZZ", "Mystery Co", "6", "LSE", "NEW", "Idea", "E Five", ""],
]


@pytest.fixture
def fake_rows():
    return [list(r) for r in FAKE_ROWS]
