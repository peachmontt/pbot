"""
AI signal store backed by SQLite.

Stores LLM-generated trading signals with TTL-based expiry.
Used by ai_research.py (write) and strategies/model_3.py (read).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "data" / "signals.db"


@dataclass
class AISignal:
    """Structured trading signal produced by the AI research worker."""

    condition_id: str
    decision: str           # BUY_YES | BUY_NO | WATCH | DO_NOT_TRADE
    confidence: float       # 0.0 – 1.0
    attention_score: float  # 0.0 – 1.0
    entry_min: float
    entry_max: float
    take_profit: float
    stop_loss: float
    time_horizon_min: int
    reason_short: str
    tradeable_now: bool
    ttl_sec: int
    created_at: float = 0.0

    def is_expired(self) -> bool:
        if self.created_at <= 0:
            return True
        return (time.time() - self.created_at) > self.ttl_sec

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AISignal:
        valid_keys = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid_keys})


class SignalStore:
    """SQLite-backed store for AI signals with automatic TTL expiry."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = str(db_path or DB_PATH)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS signals ("
            "  condition_id TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL,"
            "  created_at REAL NOT NULL,"
            "  expires_at REAL NOT NULL"
            ")",
        )
        self._conn.commit()

    def upsert(self, signal: AISignal) -> None:
        """Insert or update a signal, stamping created_at to now."""
        signal.created_at = time.time()
        expires_at = signal.created_at + signal.ttl_sec
        self._conn.execute(
            "INSERT OR REPLACE INTO signals (condition_id, data, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (signal.condition_id, json.dumps(signal.to_dict()), signal.created_at, expires_at),
        )
        self._conn.commit()

    def get(self, condition_id: str) -> AISignal | None:
        """Return a fresh signal for the given market, or None if missing/expired."""
        row = self._conn.execute(
            "SELECT data FROM signals WHERE condition_id = ? AND expires_at > ?",
            (condition_id, time.time()),
        ).fetchone()
        if not row:
            return None
        return AISignal.from_dict(json.loads(row["data"]))

    def get_all_fresh(self) -> list[AISignal]:
        """Return all signals that haven't expired yet."""
        rows = self._conn.execute(
            "SELECT data FROM signals WHERE expires_at > ?", (time.time(),),
        ).fetchall()
        return [AISignal.from_dict(json.loads(r["data"])) for r in rows]

    def prune_expired(self) -> int:
        """Delete expired signals. Returns count removed."""
        cursor = self._conn.execute(
            "DELETE FROM signals WHERE expires_at <= ?", (time.time(),),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
