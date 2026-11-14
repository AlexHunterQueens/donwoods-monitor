# Donwoods Capital Coverage Monitor

Every Saturday at 8 AM Toronto time, this tool reads the team coverage list. It checks every covered name and writes a monitor sheet showing which names each sector pair should look at before Sunday's 1 PM meeting.

* **Reads:** "Sector Coverage List - Donwoods Capital". Read only, never written.
* **Writes:** "Coverage Monitor - Donwoods Capital". Tabs: Summary, one per sector, Digest, Dropped, Run log.
* **Data:** prices and earnings dates come from Yahoo Finance via yfinance. Filings come from SEC EDGAR. SEDAR+ is not scraped, so names listed only in Canada say "check SEDAR+ manually".

## Flags

All thresholds live in `config.yaml`.

| Flag | Rule |
|---|---|
| Big move | Weekly move of 5% or more either way, or 3 pp or more vs its index (TSX for TSX listings, S&P 500 for US listings) over the same week |
| Earnings soon | Earnings in the next 14 days. Uses the yfinance date. If that is missing, uses the list's Next earnings column, marked "from list, unconfirmed" |
| New filing | 8-K, 10-Q, 10-K, 6-K or 40-F on EDGAR in the last 7 days (amendments count) |
| 52W extreme | Within 2% of the 52 week high or low |
| Report owed | Status is "In progress" and the name has a Big move or New filing |

**How the numbers are worked out**

* **1W:** the last close vs the last close on or before 7 calendar days earlier. The TSX uses the same dates.
* **1M:** the same, but one calendar month back.
* **52W high and low:** daily highs and lows over the last 365 days, which matches Yahoo's range.
* **Prices:** unadjusted closes in the listing currency, CAD for TSX and USD for US.
* Each name is compared with its own market: TSX listings vs the S&P/TSX Composite (^GSPTSE), US listings vs the S&P 500 (^GSPC). The Index column says which.

## Change a threshold

1. Edit `config.yaml`, for example `flags.big_move.weekly_pct: 6.0`.
2. Commit and push to `main`.

The next run uses the new value.

## Change the coverage list

Edit the Google Sheet. Nothing else is needed: the tool reads it fresh every run.

* Columns are found by header name, so you can reorder them or add new ones.
* Sector, Company, Ticker and Exchange must exist. If one is missing, the run stops and says which.
* Exchange values: `TSX`, `TSX / NYSE`, `TSX / NASDAQ`, `NYSE`, `NASDAQ`. A US line with a different ticker goes in brackets: `TSX / NYSE (CCJ)`.
* If a ticker won't map or price, add it to `ticker_overrides` in `config.yaml`.

## Setup

### 1. Python

```bash
python3.12 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt pytest
```

```bash
python -m pytest -q
```

### 2. Google service account

1. Go to console.cloud.google.com and create a project, for example `donwoods-monitor`.
2. Go to APIs and Services, then Library, and enable the **Google Sheets API**.
3. Go to IAM and Admin, then Service Accounts, and click Create. Name it `coverage-monitor`. Grant it no roles.
4. Open the service account, go to Keys, then Add key, then JSON. A file downloads.
5. Move the file **outside this repo**, for example `~/.config/donwoods/sa.json`. Never commit it, paste it in chat or email it.
6. Copy the service account email. It ends in `iam.gserviceaccount.com`.
7. Share the coverage list with that email as **Viewer**.
8. Create a blank Google Sheet named "Coverage Monitor - Donwoods Capital" in the same Drive folder. Share it with that email as **Editor**.
9. Put the monitor sheet ID (the long part of its URL) in `config.yaml` under `sheets.monitor_sheet_id`.

### 3. Run locally

Set these two environment variables first:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/donwoods/sa.json
```

```bash
export EDGAR_CONTACT_EMAIL=alex.hunter@queensu.ca   # optional, config.yaml already has it
```

Dry run (prints everything, writes nothing):

```bash
python -m donwoods_monitor --dry-run
```

Dry run for one sector:

```bash
python -m donwoods_monitor --dry-run --sector TMT
```

Real write. It reads the sheet back afterwards and checks the row counts:

```bash
python -m donwoods_monitor
```

### 4. GitHub Actions

1. In the repo, go to Settings, then Secrets and variables, then Actions. Add three secrets:
   * `GCP_SA_KEY`: the whole contents of the JSON key file
   * `EDGAR_CONTACT_EMAIL` (optional: config.yaml already has it)
   * `MONITOR_SHEET_ID`
2. Merge to `main`. GitHub only runs schedules from the default branch.
3. To run it by hand: Actions, then Coverage Monitor, then Run workflow. Tick "Dry run" to print without writing.

Each run uploads `digest.txt` as a run artifact.

## Safety rules the code follows

* **The coverage list:** opened only to read it. Writing refuses to run if the monitor ID equals the coverage ID.
* **Permissions:** the service account uses the Sheets scope only, with no Drive access, so it cannot delete files.
* **Rewriting tabs:** tabs are cleared and rewritten, never deleted.
* **Removed sectors:** the tool keeps the tab and reports it. It deletes the tab only with `--confirm-delete-tab NAME`, and only for tabs it created.
* **Dropped and Run log:** these tabs are append only.
