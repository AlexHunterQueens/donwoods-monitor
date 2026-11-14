"""Exchange mapping. All ticker logic lives in map_listing()."""
from __future__ import annotations

import re
from dataclasses import dataclass

US_EXCHANGES = {"NYSE", "NASDAQ", "NYSE AMERICAN", "AMEX", "NYSEARCA"}
CA_SUFFIX = {"TSX": ".TO", "TSXV": ".V", "TSX-V": ".V", "TSX V": ".V", "CSE": ".CN"}

# Built in fixes for symbols Yahoo spells differently. config.yaml can add more.
BUILTIN_OVERRIDES: dict[str, dict[str, str]] = {}


@dataclass(frozen=True)
class Listing:
    primary: str          # Yahoo Finance symbol to price
    us_ticker: str | None  # US line, used for SEC EDGAR; None if Canadian only
    currency: str         # "CAD" or "USD"
    venue: str            # exchange of the primary listing


class MappingError(ValueError):
    pass


def _yahoo(sym: str) -> str:
    # Yahoo uses a dash for share classes: RCI.B -> RCI-B, BRK.B -> BRK-B
    return sym.strip().upper().replace(".", "-")


def map_listing(ticker: str, exchange: str, overrides: dict | None = None) -> Listing:
    """Turn a coverage list Ticker and Exchange into the symbols we query.

    "TSX" or "TSX / NYSE": TSX line (.TO) is primary because the benchmark is the TSX.
    "NYSE" or "NASDAQ": plain ticker.
    "TSX / NYSE (CCJ)": TSX line of the listed ticker is primary, CCJ is the US line.
    """
    raw_ticker = (ticker or "").strip().upper()
    if not raw_ticker:
        raise MappingError("blank ticker")

    table = {**BUILTIN_OVERRIDES, **{k.upper(): v for k, v in (overrides or {}).items()}}
    exch = (exchange or "").strip().upper()

    bracket = re.search(r"\(([^)]+)\)", exch)
    us_alias = bracket.group(1).strip().upper() if bracket else None
    venues = [v.strip() for v in re.sub(r"\([^)]*\)", "", exch).split("/") if v.strip()]

    ca_venue = next((v for v in venues if v in CA_SUFFIX), None)
    us_venue = next((v for v in venues if v in US_EXCHANGES), None)

    if ca_venue:
        listing = Listing(
            primary=_yahoo(raw_ticker) + CA_SUFFIX[ca_venue],
            us_ticker=us_alias or (raw_ticker if us_venue else None),
            currency="CAD",
            venue=ca_venue,
        )
    elif us_venue:
        listing = Listing(primary=_yahoo(raw_ticker), us_ticker=us_alias or raw_ticker,
                          currency="USD", venue=us_venue)
    elif raw_ticker in table:
        listing = Listing(primary="", us_ticker=None, currency="", venue=exch)
    else:
        raise MappingError(f"unknown exchange '{exchange}'")

    if raw_ticker in table:
        o = table[raw_ticker]
        us = o.get("us", listing.us_ticker)
        listing = Listing(
            primary=o.get("primary", listing.primary),
            us_ticker=(us or None),
            currency=o.get("currency", listing.currency),
            venue=o.get("venue", listing.venue),
        )
    if not listing.primary:
        raise MappingError(f"override for {raw_ticker} has no primary symbol")
    return listing
