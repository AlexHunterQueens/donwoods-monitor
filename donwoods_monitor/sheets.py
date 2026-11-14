"""Google Sheets IO. The coverage list is only ever read."""
from __future__ import annotations

import logging
import os

from .monitor import SECTOR_MARKER

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]  # Sheets only, no Drive access
FIXED_TABS = ["Summary", "Digest", "Dropped", "Run log"]


def client():
    import gspread
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path or not os.path.isfile(path):
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS to the service account key file "
                           "(kept outside the repo folder)")
    return gspread.service_account(filename=path, scopes=SCOPES)


def read_coverage(gc, sheet_id: str, tab: str = "") -> list[list[str]]:
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet(tab) if tab else sh.get_worksheet(0)
    return ws.get_all_values()  # read only: nothing in this module writes to this sheet


class MonitorSheet:
    def __init__(self, gc, sheet_id: str, coverage_id: str):
        if not sheet_id:
            raise RuntimeError("sheets.monitor_sheet_id is blank in config.yaml")
        if sheet_id == coverage_id:
            raise RuntimeError("monitor_sheet_id equals the coverage list ID. Refusing to write.")
        self.sh = gc.open_by_key(sheet_id)
        self._tabs = {ws.title: ws for ws in self.sh.worksheets()}

    # ----- reading -----
    def tool_sector_tabs(self) -> dict:
        out = {}
        for title, ws in self._tabs.items():
            if title in FIXED_TABS:
                continue
            a1 = ws.acell("A1").value or ""
            if a1.startswith(SECTOR_MARKER):
                out[title] = ws
        return out

    def previous_roster(self) -> list[tuple[str, str, str]]:
        """(sector, company, ticker) from last run's sector tabs."""
        roster = []
        for title, ws in self.tool_sector_tabs().items():
            for row in ws.get_all_values()[2:]:
                if len(row) > 1 and row[1].strip():
                    roster.append((title, row[0], row[1].strip().upper()))
        return roster

    def scheduled_run_today(self, today_iso: str) -> bool:
        ws = self._tabs.get("Run log")
        if not ws:
            return False
        return any(r and r[0].startswith(today_iso) and len(r) > 1 and r[1] == "scheduled"
                   for r in ws.get_all_values()[2:])

    # ----- writing -----
    def _get_or_add(self, title: str, rows: int, cols: int):
        ws = self._tabs.get(title)
        if ws is None:
            ws = self.sh.add_worksheet(title=title, rows=max(rows, 50), cols=max(cols, 10))
            self._tabs[title] = ws
        return ws

    def rewrite(self, title: str, source: str, headers: list[str] | None, rows: list[list]):
        """Clear and rewrite cells. Never deletes the tab."""
        values = [[source]] + ([headers] if headers else []) + rows
        width = max(len(v) for v in values)
        ws = self._get_or_add(title, len(values) + 10, width)
        if ws.row_count < len(values) or ws.col_count < width:
            ws.resize(rows=max(ws.row_count, len(values) + 10), cols=max(ws.col_count, width))
        ws.clear()
        ws.update(values=values, range_name="A1", value_input_option="RAW")
        if headers:
            ws.freeze(rows=2)
            ws.format("2:2", {"textFormat": {"bold": True}})

    def append(self, title: str, source: str, headers: list[str], rows: list[list]):
        """Append only. Existing history is never touched."""
        ws = self._get_or_add(title, 100, len(headers))
        if not (ws.acell("A1").value or "").strip():
            ws.update(values=[[source], headers], range_name="A1", value_input_option="RAW")
            ws.freeze(rows=2)
            ws.format("2:2", {"textFormat": {"bold": True}})
        if rows:
            ws.append_rows(rows, value_input_option="RAW", table_range="A2")

    def delete_tab(self, title: str):
        """Only called for a tool made sector tab, and only with explicit confirmation."""
        ws = self.tool_sector_tabs().get(title)
        if ws is None:
            raise RuntimeError(f"'{title}' is not a sector tab this tool created. Not deleting.")
        self.sh.del_worksheet(ws)
        self._tabs.pop(title, None)

    def tab_rows(self, title: str) -> list[list[str]]:
        ws = self.sh.worksheet(title)
        return ws.get_all_values()
