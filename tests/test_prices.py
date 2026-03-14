from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from analyzer.api.prices import fetch_prices_batch
from analyzer.db.repository import Repository
from analyzer.db.schema import ALL_TABLES, INDEXES


# ── helpers ───────────────────────────────────────────────────────────


def _init_test_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    for ddl in ALL_TABLES:
        conn.execute(ddl)
    for idx in INDEXES:
        conn.execute(idx)
    conn.commit()
    conn.close()


def _insert_trade(repo: Repository, wallet: str, asset: str) -> None:
    repo.insert_trades([{
        "wallet": wallet,
        "proxy_wallet": None,
        "side": "BUY",
        "asset": asset,
        "condition_id": "cond1",
        "size": 10.0,
        "price": 0.5,
        "timestamp": 1000,
        "title": "test",
        "slug": "test",
        "event_slug": "test",
        "outcome": "Yes",
        "outcome_index": 0,
        "tx_hash": f"tx_{asset}",
        "fetched_at": 2000,
    }])


# ── Repository.get_assets_missing_prices ──────────────────────────────


class TestGetAssetsMissingPrices:
    def test_all_missing_when_no_price_history(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _init_test_db(db)
        with Repository(db) as repo:
            _insert_trade(repo, "w1", "asset_a")
            _insert_trade(repo, "w1", "asset_b")
            missing = repo.get_assets_missing_prices("w1")

        assert sorted(missing) == ["asset_a", "asset_b"]

    def test_excludes_cached_assets(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _init_test_db(db)
        with Repository(db) as repo:
            _insert_trade(repo, "w1", "asset_a")
            _insert_trade(repo, "w1", "asset_b")
            repo.insert_price_history("asset_a", [{"timestamp": 100, "price": 0.5}])
            missing = repo.get_assets_missing_prices("w1")

        assert missing == ["asset_b"]

    def test_empty_when_all_cached(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _init_test_db(db)
        with Repository(db) as repo:
            _insert_trade(repo, "w1", "asset_a")
            repo.insert_price_history("asset_a", [{"timestamp": 100, "price": 0.5}])
            missing = repo.get_assets_missing_prices("w1")

        assert missing == []

    def test_scoped_to_wallet(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        _init_test_db(db)
        with Repository(db) as repo:
            _insert_trade(repo, "w1", "asset_a")
            _insert_trade(repo, "w2", "asset_b")
            missing = repo.get_assets_missing_prices("w1")

        assert missing == ["asset_a"]


# ── fetch_prices_batch ────────────────────────────────────────────────


def _make_mock_client(responses: dict[str, list[dict]]) -> MagicMock:
    """Create a mock PolymarketClient where .get returns per-asset history."""
    client = MagicMock()

    async def mock_get(path: str, params: dict | None = None) -> tuple:
        asset_id = params.get("market", "") if params else ""
        if asset_id in responses:
            return {"history": responses[asset_id]}, None
        return None, Exception("not found")

    client.get = AsyncMock(side_effect=mock_get)
    return client


class TestFetchPricesBatch:
    def test_fetches_multiple_assets_concurrently(self) -> None:
        responses = {
            "a1": [{"t": 100, "p": 0.5}],
            "a2": [{"t": 200, "p": 0.6}],
        }
        client = _make_mock_client(responses)

        result = asyncio.run(
            fetch_prices_batch(client, ["a1", "a2"], start_ts=0, end_ts=86400)
        )

        assert "a1" in result
        assert "a2" in result
        assert result["a1"] == [{"t": 100, "p": 0.5}]

    def test_skips_assets_with_no_data(self) -> None:
        responses = {"a1": [{"t": 100, "p": 0.5}]}
        client = _make_mock_client(responses)

        result = asyncio.run(
            fetch_prices_batch(client, ["a1", "missing"], start_ts=0, end_ts=86400)
        )

        assert "a1" in result
        assert "missing" not in result

    def test_empty_asset_list(self) -> None:
        client = _make_mock_client({})
        result = asyncio.run(
            fetch_prices_batch(client, [], start_ts=0, end_ts=86400)
        )
        assert result == {}

    def test_progress_callback_called(self) -> None:
        responses = {"a1": [{"t": 100, "p": 0.5}]}
        client = _make_mock_client(responses)
        calls: list[tuple[int, int]] = []

        result = asyncio.run(
            fetch_prices_batch(
                client, ["a1"], start_ts=0, end_ts=86400,
                on_progress=lambda done, total: calls.append((done, total)),
            )
        )

        assert len(calls) >= 1
        assert calls[-1] == (1, 1)
