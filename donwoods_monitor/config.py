"""Load config.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path or os.environ.get("MONITOR_CONFIG") or DEFAULT_PATH)
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # Environment overrides, so Actions can set values without editing the file.
    env_email = os.environ.get("EDGAR_CONTACT_EMAIL")
    if env_email:
        cfg.setdefault("edgar", {})["contact_email"] = env_email
    env_monitor = os.environ.get("MONITOR_SHEET_ID")
    if env_monitor:
        cfg.setdefault("sheets", {})["monitor_sheet_id"] = env_monitor
    cfg.setdefault("ticker_overrides", {})
    cfg["ticker_overrides"] = cfg["ticker_overrides"] or {}
    return cfg
