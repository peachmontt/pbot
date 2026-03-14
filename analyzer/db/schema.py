from __future__ import annotations

import sqlite3
from pathlib import Path

RAW_TRADES_TABLE = """\
CREATE TABLE IF NOT EXISTS raw_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    proxy_wallet TEXT,
    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
    asset TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    timestamp INTEGER NOT NULL,
    title TEXT,
    slug TEXT,
    event_slug TEXT,
    outcome TEXT,
    outcome_index INTEGER,
    tx_hash TEXT,
    fetched_at INTEGER NOT NULL,
    UNIQUE(wallet, tx_hash, asset, side, timestamp)
);
"""

ACTIVITY_TABLE = """\
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    proxy_wallet TEXT,
    type TEXT NOT NULL,
    side TEXT,
    asset TEXT,
    condition_id TEXT NOT NULL,
    size REAL,
    usdc_size REAL,
    price REAL,
    timestamp INTEGER NOT NULL,
    title TEXT,
    slug TEXT,
    event_slug TEXT,
    outcome TEXT,
    outcome_index INTEGER,
    tx_hash TEXT,
    fetched_at INTEGER NOT NULL,
    UNIQUE(wallet, tx_hash, type, asset, timestamp)
);
"""

MARKETS_TABLE = """\
CREATE TABLE IF NOT EXISTS markets (
    condition_id TEXT PRIMARY KEY,
    title TEXT,
    slug TEXT,
    event_slug TEXT,
    category TEXT,
    end_date TEXT,
    is_active INTEGER DEFAULT 1,
    outcomes TEXT,
    tokens TEXT,
    fetched_at INTEGER
);
"""

PRICE_HISTORY_TABLE = """\
CREATE TABLE IF NOT EXISTS price_history (
    asset TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    price REAL NOT NULL,
    PRIMARY KEY (asset, timestamp)
);
"""

ROUNDS_TABLE = """\
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    asset TEXT NOT NULL,
    entry_time INTEGER,
    exit_time INTEGER,
    avg_entry_price REAL,
    avg_exit_price REAL,
    max_size REAL,
    total_bought REAL,
    total_sold REAL,
    num_entries INTEGER DEFAULT 0,
    num_exits INTEGER DEFAULT 0,
    realized_pnl REAL,
    hold_duration_sec INTEGER,
    is_closed INTEGER DEFAULT 0,
    mfe REAL,
    mae REAL,
    edge_captured REAL
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_trades_wallet ON raw_trades(wallet);",
    "CREATE INDEX IF NOT EXISTS idx_trades_wallet_condition ON raw_trades(wallet, condition_id);",
    "CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON raw_trades(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_activity_wallet ON activity(wallet);",
    "CREATE INDEX IF NOT EXISTS idx_activity_type ON activity(type);",
    "CREATE INDEX IF NOT EXISTS idx_rounds_wallet ON rounds(wallet);",
    "CREATE INDEX IF NOT EXISTS idx_rounds_condition ON rounds(wallet, condition_id);",
]

ALL_TABLES = [
    RAW_TRADES_TABLE,
    ACTIVITY_TABLE,
    MARKETS_TABLE,
    PRICE_HISTORY_TABLE,
    ROUNDS_TABLE,
]


async def init_db(db_path: Path) -> None:
    """Create the database file (and parent dirs) and execute all DDL statements."""
    import asyncio

    def _init_sync() -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            for table_ddl in ALL_TABLES:
                conn.execute(table_ddl)
            for index_ddl in INDEXES:
                conn.execute(index_ddl)
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_init_sync)
