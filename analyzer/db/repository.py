from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self


class Repository:
    _conn: sqlite3.Connection

    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    # ── Inserts ──────────────────────────────────────────────────────

    def insert_trades(self, trades: list[dict[str, object]]) -> int:
        if not trades:
            return 0
        cols = [
            "wallet", "proxy_wallet", "side", "asset", "condition_id",
            "size", "price", "timestamp", "title", "slug", "event_slug",
            "outcome", "outcome_index", "tx_hash", "fetched_at",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT OR IGNORE INTO raw_trades ({', '.join(cols)}) VALUES ({placeholders})"
        rows = [tuple(t.get(c) for c in cols) for t in trades]
        cur = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cur.rowcount

    def insert_activity(self, activities: list[dict[str, object]]) -> int:
        if not activities:
            return 0
        cols = [
            "wallet", "proxy_wallet", "type", "side", "asset", "condition_id",
            "size", "usdc_size", "price", "timestamp", "title", "slug",
            "event_slug", "outcome", "outcome_index", "tx_hash", "fetched_at",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT OR IGNORE INTO activity ({', '.join(cols)}) VALUES ({placeholders})"
        rows = [tuple(a.get(c) for c in cols) for a in activities]
        cur = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cur.rowcount

    def insert_market(self, market: dict[str, object]) -> None:
        cols = [
            "condition_id", "title", "slug", "event_slug", "category",
            "end_date", "is_active", "outcomes", "tokens", "fetched_at",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT OR REPLACE INTO markets ({', '.join(cols)}) VALUES ({placeholders})"
        self._conn.execute(sql, tuple(market.get(c) for c in cols))
        self._conn.commit()

    def insert_price_history(self, asset: str, prices: list[dict[str, object]]) -> int:
        if not prices:
            return 0
        sql = "INSERT OR IGNORE INTO price_history (asset, timestamp, price) VALUES (?, ?, ?)"
        rows = [(asset, p["timestamp"], p["price"]) for p in prices]
        cur = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cur.rowcount

    def insert_rounds(self, rounds: list[dict[str, object]]) -> int:
        if not rounds:
            return 0
        cols = [
            "wallet", "condition_id", "outcome", "asset", "entry_time",
            "exit_time", "avg_entry_price", "avg_exit_price", "max_size",
            "total_bought", "total_sold", "num_entries", "num_exits",
            "realized_pnl", "hold_duration_sec", "is_closed", "mfe",
            "mae", "edge_captured",
        ]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO rounds ({', '.join(cols)}) VALUES ({placeholders})"
        rows = [tuple(r.get(c) for c in cols) for r in rounds]
        cur = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cur.rowcount

    # ── Queries ──────────────────────────────────────────────────────

    def get_trades(
        self, wallet: str, condition_id: str | None = None
    ) -> list[dict[str, object]]:
        if condition_id is not None:
            sql = (
                "SELECT * FROM raw_trades "
                "WHERE wallet = ? AND condition_id = ? ORDER BY timestamp ASC"
            )
            rows = self._conn.execute(sql, (wallet, condition_id)).fetchall()
        else:
            sql = "SELECT * FROM raw_trades WHERE wallet = ? ORDER BY timestamp ASC"
            rows = self._conn.execute(sql, (wallet,)).fetchall()
        return [dict(r) for r in rows]

    def get_activity(
        self, wallet: str, types: list[str] | None = None
    ) -> list[dict[str, object]]:
        if types:
            placeholders = ", ".join(["?"] * len(types))
            sql = (
                f"SELECT * FROM activity "
                f"WHERE wallet = ? AND type IN ({placeholders}) ORDER BY timestamp ASC"
            )
            rows = self._conn.execute(sql, [wallet, *types]).fetchall()
        else:
            sql = "SELECT * FROM activity WHERE wallet = ? ORDER BY timestamp ASC"
            rows = self._conn.execute(sql, (wallet,)).fetchall()
        return [dict(r) for r in rows]

    def get_market(self, condition_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM markets WHERE condition_id = ?", (condition_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_markets(self) -> list[dict[str, object]]:
        rows = self._conn.execute("SELECT * FROM markets").fetchall()
        return [dict(r) for r in rows]

    def get_price_history(
        self,
        asset: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[dict[str, object]]:
        conditions = ["asset = ?"]
        params: list[str | int] = [asset]
        if start_ts is not None:
            conditions.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("timestamp <= ?")
            params.append(end_ts)
        sql = (
            f"SELECT * FROM price_history "
            f"WHERE {' AND '.join(conditions)} ORDER BY timestamp ASC"
        )
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_rounds(self, wallet: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM rounds WHERE wallet = ? ORDER BY entry_time ASC",
            (wallet,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unique_condition_ids(self, wallet: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT condition_id FROM raw_trades WHERE wallet = ? ORDER BY condition_id",
            (wallet,),
        ).fetchall()
        return [row["condition_id"] for row in rows]

    def get_unique_assets(self, wallet: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT asset FROM raw_trades WHERE wallet = ? ORDER BY asset",
            (wallet,),
        ).fetchall()
        return [row["asset"] for row in rows]

    def get_assets_missing_prices(self, wallet: str) -> list[str]:
        """Return assets for a wallet that have no rows in price_history yet."""
        rows = self._conn.execute(
            "SELECT DISTINCT t.asset FROM raw_trades t "
            "LEFT JOIN price_history p ON t.asset = p.asset "
            "WHERE t.wallet = ? AND p.asset IS NULL "
            "ORDER BY t.asset",
            (wallet,),
        ).fetchall()
        return [row["asset"] for row in rows]

    def get_trade_count(self, wallet: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM raw_trades WHERE wallet = ?", (wallet,)
        ).fetchone()
        return row["cnt"] if row else 0

    def clear_rounds(self, wallet: str) -> None:
        self._conn.execute("DELETE FROM rounds WHERE wallet = ?", (wallet,))
        self._conn.commit()
