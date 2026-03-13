"""
Trade journal: appends every trade event to a CSV file for analysis.

Columns: timestamp, market, asset, leg, action, price, size, pnl, notes
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_PATH = Path(__file__).resolve().parent / "trade_journal.csv"

COLUMNS = [
    "timestamp",
    "market",
    "asset",
    "condition_id",
    "leg",
    "action",
    "entry_price",
    "exit_price",
    "size",
    "pnl",
    "notes",
]


def _ensure_header() -> None:
    if not JOURNAL_PATH.exists() or JOURNAL_PATH.stat().st_size == 0:
        with open(JOURNAL_PATH, "w", newline="") as f:
            csv.writer(f).writerow(COLUMNS)


def log_event(
    market: str,
    asset: str,
    condition_id: str,
    leg: str,
    action: str,
    entry_price: float = 0.0,
    exit_price: float = 0.0,
    size: float = 0.0,
    pnl: float = 0.0,
    notes: str = "",
) -> None:
    """Append a single trade event row to the journal CSV."""
    _ensure_header()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(JOURNAL_PATH, "a", newline="") as f:
        csv.writer(f).writerow([
            ts, market, asset, condition_id, leg, action,
            f"{entry_price:.4f}", f"{exit_price:.4f}",
            f"{size:.1f}", f"{pnl:.4f}", notes,
        ])
