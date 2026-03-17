"""Tests for signal_store, ai_research prefilter, and model_3 compute_levels."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from signal_store import AISignal, SignalStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    condition_id: str = "cond1",
    decision: str = "BUY_YES",
    confidence: float = 0.80,
    attention: float = 0.85,
    entry_min: float = 0.40,
    entry_max: float = 0.50,
    tp: float = 0.60,
    sl: float = 0.35,
    tradeable: bool = True,
    ttl: int = 90,
) -> AISignal:
    return AISignal(
        condition_id=condition_id,
        decision=decision,
        confidence=confidence,
        attention_score=attention,
        entry_min=entry_min,
        entry_max=entry_max,
        take_profit=tp,
        stop_loss=sl,
        time_horizon_min=30,
        reason_short="test signal",
        tradeable_now=tradeable,
        ttl_sec=ttl,
    )


def _make_market(
    yes_price: float = 0.45,
    condition_id: str = "cond1",
) -> dict:
    return {
        "question": "Will X happen?",
        "asset": "",
        "condition_id": condition_id,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "yes_price": yes_price,
        "no_price": round(1 - yes_price, 4),
    }


# ---------------------------------------------------------------------------
# SignalStore
# ---------------------------------------------------------------------------

class TestSignalStore:
    @pytest.fixture(autouse=True)
    def _store(self, tmp_path: Path):
        self.store = SignalStore(db_path=tmp_path / "test_signals.db")
        yield
        self.store.close()

    def test_upsert_and_get(self):
        sig = _make_signal()
        self.store.upsert(sig)
        got = self.store.get("cond1")
        assert got is not None
        assert got.decision == "BUY_YES"
        assert got.confidence == 0.80

    def test_get_returns_none_for_missing(self):
        assert self.store.get("nonexistent") is None

    def test_expired_signal_returns_none(self):
        sig = _make_signal(ttl=1)
        self.store.upsert(sig)
        time.sleep(1.1)
        assert self.store.get("cond1") is None

    def test_upsert_overwrites(self):
        self.store.upsert(_make_signal(confidence=0.60))
        self.store.upsert(_make_signal(confidence=0.90))
        got = self.store.get("cond1")
        assert got is not None
        assert got.confidence == 0.90

    def test_get_all_fresh(self):
        self.store.upsert(_make_signal(condition_id="c1"))
        self.store.upsert(_make_signal(condition_id="c2"))
        fresh = self.store.get_all_fresh()
        assert len(fresh) == 2

    def test_prune_expired(self):
        sig = _make_signal(ttl=1)
        self.store.upsert(sig)
        time.sleep(1.1)
        pruned = self.store.prune_expired()
        assert pruned == 1
        assert self.store.get_all_fresh() == []


# ---------------------------------------------------------------------------
# AISignal
# ---------------------------------------------------------------------------

class TestAISignal:
    def test_round_trip_dict(self):
        sig = _make_signal()
        sig.created_at = time.time()
        rebuilt = AISignal.from_dict(sig.to_dict())
        assert rebuilt.condition_id == sig.condition_id
        assert rebuilt.confidence == sig.confidence

    def test_is_expired_no_timestamp(self):
        sig = _make_signal()
        assert sig.is_expired()

    def test_is_expired_fresh(self):
        sig = _make_signal(ttl=60)
        sig.created_at = time.time()
        assert not sig.is_expired()


# ---------------------------------------------------------------------------
# Prefilter (from ai_research)
# ---------------------------------------------------------------------------

class TestPrefilter:
    def test_filters_extreme_prices(self):
        from ai_research import prefilter

        markets = [
            {"yes_price": 0.10, "spread": 0.01, "condition_id": "c1"},
            {"yes_price": 0.50, "spread": 0.01, "condition_id": "c2"},
            {"yes_price": 0.95, "spread": 0.01, "condition_id": "c3"},
        ]
        result = prefilter(markets, top_k=10)
        assert len(result) == 1
        assert result[0]["condition_id"] == "c2"

    def test_filters_no_spread(self):
        from ai_research import prefilter

        markets = [
            {"yes_price": 0.50, "spread": None, "condition_id": "c1"},
            {"yes_price": 0.50, "spread": 0.0, "condition_id": "c2"},
            {"yes_price": 0.50, "spread": 0.02, "condition_id": "c3"},
        ]
        result = prefilter(markets, top_k=10)
        assert len(result) == 1

    def test_respects_top_k(self):
        from ai_research import prefilter

        markets = [
            {"yes_price": 0.50, "spread": 0.01 * (i + 1), "condition_id": f"c{i}"}
            for i in range(10)
        ]
        result = prefilter(markets, top_k=3)
        assert len(result) == 3
        assert result[0]["spread"] == 0.01

    def test_sorts_by_tightest_spread(self):
        from ai_research import prefilter

        markets = [
            {"yes_price": 0.50, "spread": 0.05, "condition_id": "wide"},
            {"yes_price": 0.50, "spread": 0.01, "condition_id": "tight"},
        ]
        result = prefilter(markets, top_k=10)
        assert result[0]["condition_id"] == "tight"


# ---------------------------------------------------------------------------
# model_3 compute_levels
# ---------------------------------------------------------------------------

class TestModel3ComputeLevels:
    @pytest.fixture(autouse=True)
    def _store(self, tmp_path: Path):
        store = SignalStore(db_path=tmp_path / "m3_test.db")
        with patch("ai_research._store", store):
            yield store
        store.close()

    def test_returns_levels_for_valid_yes_signal(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(decision="BUY_YES"))
        levels = compute_levels(_make_market(yes_price=0.45))
        assert levels is not None
        assert levels.buy_yes_price == 0.45
        assert levels.sell_yes_price == 0.60
        assert levels.buy_no_price == 0.0

    def test_returns_levels_for_valid_no_signal(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(
            decision="BUY_NO",
            entry_min=0.50, entry_max=0.60, tp=0.70, sl=0.40,
        ))
        levels = compute_levels(_make_market(yes_price=0.45))
        assert levels is not None
        assert levels.buy_no_price == 0.55
        assert levels.buy_yes_price == 0.0

    def test_returns_none_when_no_signal(self, _store):
        from strategies.model_3 import compute_levels

        assert compute_levels(_make_market()) is None

    def test_returns_none_for_low_confidence(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(confidence=0.30))
        assert compute_levels(_make_market()) is None

    def test_returns_none_for_low_attention(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(attention=0.40))
        assert compute_levels(_make_market()) is None

    def test_returns_none_when_not_tradeable(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(tradeable=False))
        assert compute_levels(_make_market()) is None

    def test_returns_none_when_price_outside_entry_zone(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(entry_min=0.60, entry_max=0.70))
        assert compute_levels(_make_market(yes_price=0.45)) is None

    def test_returns_none_for_watch_decision(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(decision="WATCH"))
        assert compute_levels(_make_market()) is None

    def test_returns_none_for_negative_expected_profit(self, _store):
        from strategies.model_3 import compute_levels

        _store.upsert(_make_signal(tp=0.46))
        assert compute_levels(_make_market(yes_price=0.45)) is None
