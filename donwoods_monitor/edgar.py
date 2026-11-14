"""New filings from the free SEC EDGAR JSON API."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


@dataclass
class Filing:
    form: str
    filed: date
    url: str


class Edgar:
    def __init__(self, org: str, email: str, session: requests.Session | None = None):
        if not email or "@" not in email:
            raise ValueError("EDGAR needs a contact email: set edgar.contact_email in config.yaml "
                             "or the EDGAR_CONTACT_EMAIL environment variable")
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": f"{org} {email}", "Accept-Encoding": "gzip, deflate"})
        self._ciks: dict[str, int] | None = None

    def _get(self, url: str) -> dict:
        for attempt in range(3):
            r = self.s.get(url, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            time.sleep(0.15)  # SEC asks for at most 10 requests a second
            return r.json()
        r.raise_for_status()
        return {}

    def cik_for(self, ticker: str) -> int | None:
        if self._ciks is None:
            data = self._get(TICKERS_URL)
            self._ciks = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
        t = ticker.upper()
        return self._ciks.get(t) or self._ciks.get(t.replace(".", "-"))

    def recent_filings(self, cik: int, today: date, lookback_days: int,
                       forms: list[str], include_amendments: bool = True) -> list[Filing]:
        data = self._get(SUBMISSIONS_URL.format(cik=cik))
        return filter_filings(data, cik, today, lookback_days, forms, include_amendments)


def filter_filings(data: dict, cik: int, today: date, lookback_days: int,
                   forms: list[str], include_amendments: bool = True) -> list[Filing]:
    recent = (data.get("filings") or {}).get("recent") or {}
    wanted = {f.upper() for f in forms}
    if include_amendments:
        wanted |= {f + "/A" for f in wanted}
    since = today - timedelta(days=lookback_days)
    out = []
    for form, filed, acc, doc in zip(recent.get("form", []), recent.get("filingDate", []),
                                     recent.get("accessionNumber", []),
                                     recent.get("primaryDocument", [])):
        if form.upper() not in wanted:
            continue
        d = date.fromisoformat(filed)
        if since < d <= today:
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                   f"{acc.replace('-', '')}/{doc}")
            out.append(Filing(form=form, filed=d, url=url))
    return sorted(out, key=lambda f: f.filed, reverse=True)
