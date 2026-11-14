"""Command line entry point.

  python -m donwoods_monitor --dry-run                 print everything, write nothing
  python -m donwoods_monitor --dry-run --sector TMT    print one sector
  python -m donwoods_monitor                           write to the monitor sheet
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import monitor as M
from .config import load_config
from .coverage import CoverageError, parse_coverage


def _args(argv):
    p = argparse.ArgumentParser(prog="donwoods-monitor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="print output, write nothing")
    p.add_argument("--sector", help="dry run only: show just this sector")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("--coverage-csv", help="read the coverage list from a CSV export instead of Sheets")
    p.add_argument("--no-edgar", action="store_true", help="skip SEC EDGAR lookups")
    p.add_argument("--scheduled", action="store_true",
                   help="used by GitHub Actions: run only at the configured Toronto hour, once a day")
    p.add_argument("--confirm-delete-tab", action="append", default=[], metavar="TAB",
                   help="delete this stale sector tab (only tabs this tool created)")
    p.add_argument("--out", default="out", help="folder for digest.txt and CSV copies")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = _args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    cfg = load_config(a.config)
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    now = datetime.now(tz)
    today = now.date()

    if a.sector and not a.dry_run:
        print("--sector works with --dry-run only. A partial write would mark other names as dropped.")
        return 2
    if a.scheduled and now.hour != int(cfg["schedule"]["hour"]):
        print(f"Scheduled run skipped: it is {now:%H:%M} in Toronto, not {cfg['schedule']['hour']}:00.")
        return 0

    gc = None
    if not a.coverage_csv or not a.dry_run:
        from .sheets import client
        gc = client()

    # 1. Coverage list, fresh every run, read only
    if a.coverage_csv:
        with open(a.coverage_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    else:
        from .sheets import read_coverage
        rows = read_coverage(gc, cfg["sheets"]["coverage_sheet_id"], cfg["sheets"].get("coverage_tab", ""))
    try:
        names = parse_coverage(rows, cfg)
    except CoverageError as e:
        print(f"STOPPED: {e}")
        return 1
    if a.sector:
        names = [n for n in names if n.sector.casefold() == a.sector.casefold()]
        if not names:
            print(f"No names in sector '{a.sector}'.")
            return 1

    sheet = None
    if not a.dry_run:
        from .sheets import MonitorSheet
        sheet = MonitorSheet(gc, cfg["sheets"]["monitor_sheet_id"], cfg["sheets"]["coverage_sheet_id"])
        if a.scheduled and sheet.scheduled_run_today(today.isoformat()):
            print("Scheduled run already done today. Skipping.")
            return 0

    # 2. Data
    from .prices import fetch_earnings_date, fetch_history
    edgar, edgar_err = None, ""
    if a.no_edgar:
        edgar_err = "--no-edgar set"
    else:
        try:
            from .edgar import Edgar
            edgar = Edgar(cfg["edgar"]["org_name"], cfg["edgar"].get("contact_email", ""))
        except ValueError as e:
            edgar_err = str(e)

    run = M.build_run(names, cfg, today, now, fetch_history=fetch_history,
                      fetch_earnings=fetch_earnings_date, edgar=edgar, edgar_error=edgar_err)

    # 3. Output
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    digest = M.digest_lines(run)
    (out / "digest.txt").write_text("\n".join(digest) + "\n", encoding="utf-8")

    if a.dry_run:
        _print_dry(run, out)
        return 0

    _write(run, sheet, a, today)
    return 0


def _print_dry(run: M.Run, out: Path):
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 60)
    print(M.source_line(run))
    print()
    for s in run.sectors:
        df = M.as_frame(M.SECTOR_HEADERS, M.sector_rows(run, s))
        df.to_csv(out / f"sector_{s.replace('&', 'and').replace('/', '_')}.csv", index=False)
        print(f"=== {s} ({len(df)} names) ===")
        print(df.to_string(index=False))
        print()
    summ = M.as_frame(M.SUMMARY_HEADERS, M.summary_rows(run))
    print(f"=== Summary ({len(summ)} flagged) ===")
    print(summ.to_string(index=False) if len(summ) else "Nothing flagged.")
    print()
    print("=== Data problems ===")
    print("\n".join(" | ".join(x for x in p if x) for p in run.problems) or "None.")
    print()
    print("=== Digest ===")
    print("\n".join(M.digest_lines(run)))
    print(f"\nDRY RUN: nothing written. CSV copies in {out}/")


def _write(run: M.Run, sheet, a, today: date):
    src = M.source_line(run)
    mode = "scheduled" if a.scheduled else "manual"

    # Dropped: compare last run's sector tabs with today's list, before rewriting them
    current = {r.name.ticker for r in run.results}
    prev = sheet.previous_roster()
    seen, dropped = set(), []
    for sec, comp, tick in prev:
        if tick not in current and tick not in seen:
            seen.add(tick)
            dropped.append([today.isoformat(), sec, comp, tick])

    # Sector tabs
    for s in run.sectors:
        sheet.rewrite(s, M.source_line(run, M.SECTOR_MARKER), M.SECTOR_HEADERS, M.sector_rows(run, s))

    # Summary: flagged names, then data problems underneath
    summ = M.summary_rows(run)
    probs = [list(p) for p in run.problems]
    body = summ + ([[""], ["Data problems"], M.PROBLEM_HEADERS] + probs if probs else [])
    sheet.rewrite("Summary", src, M.SUMMARY_HEADERS, body)

    sheet.rewrite("Digest", src, None, [[ln] for ln in M.digest_lines(run)])
    sheet.append("Dropped", "Names on the last run that are no longer on the coverage list. "
                 "Append only.", M.DROPPED_HEADERS, dropped)
    sheet.append("Run log", "One row per run. Append only.", M.RUNLOG_HEADERS, [M.runlog_row(run, mode)])

    # Sector tabs for sectors that no longer exist: report, delete only when confirmed
    stale = [t for t in sheet.tool_sector_tabs() if t not in run.sectors]
    for t in stale:
        if t in a.confirm_delete_tab:
            sheet.delete_tab(t)
            print(f"Deleted stale sector tab '{t}' (confirmed).")
        else:
            print(f"Stale sector tab '{t}': sector is gone from the list. Kept. "
                  f"Rerun with --confirm-delete-tab '{t}' to remove it.")

    # Verify by reading the sheet back, not by trusting what we sent
    ok = True
    for s in run.sectors:
        got = len(sheet.tab_rows(s)) - 2
        want = sum(1 for r in run.results if r.name.sector == s)
        status = "OK" if got == want else "MISMATCH"
        ok &= got == want
        print(f"{s}: {got} rows in sheet, {want} on coverage list, {status}")
    got_summary = 0
    for r in sheet.tab_rows("Summary")[2:]:
        if not any(c.strip() for c in r):
            break  # blank row separates flags from data problems
        got_summary += 1
    print(f"Summary: {got_summary} flagged rows, expected {len(summ)}, "
          f"{'OK' if got_summary == len(summ) else 'MISMATCH'}")
    ok &= got_summary == len(summ)
    print(f"Dropped this run: {len(dropped)}. Data problems: {len(probs)}.")
    if not ok:
        raise SystemExit("Read back check failed. See MISMATCH lines above.")


if __name__ == "__main__":
    sys.exit(main())
