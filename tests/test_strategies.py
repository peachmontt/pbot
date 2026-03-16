"""Tests for strategy modules (model_1 and model_2)."""
from __future__ import annotations

import pytest

from strategies.model_1 import compute_levels as model_1_levels
import strategies.model_2 as model_2_mod
from strategies.model_2 import (
    compute_levels as model_2_levels,
    TAKE_PROFIT_OFFSET,
    STOP_LOSS_OFFSET,
)


def _make_market(yes_price: float = 0.50, **overrides) -> dict:
    """Helper: build a minimal market dict for strategy tests."""
    base = {
        "question": "Will X happen?",
        "asset": "test-asset",
        "condition_id": "cond-123",
        "yes_token_id": "tok-yes",
        "no_token_id": "tok-no",
        "yes_price": yes_price,
        "no_price": round(1.0 - yes_price, 4),
        "price_change_5m": 0.0,
        "price_change_15m": 0.0,
    }
    base.update(overrides)
    return base


# ── model_1 tests ──────────────────────────────────────────────


class TestModel1MidPrice:
    """Mid-price 0.50 should produce valid symmetric levels."""

    def test_returns_levels(self):
        levels = model_1_levels(_make_market(0.50))
        assert levels is not None

    def test_buy_below_mid(self):
        levels = model_1_levels(_make_market(0.50))
        assert levels.buy_yes_price < 0.50
        assert levels.buy_no_price < 0.50

    def test_sell_above_buy(self):
        levels = model_1_levels(_make_market(0.50))
        assert levels.sell_yes_price > levels.buy_yes_price
        assert levels.sell_no_price > levels.buy_no_price


class TestModel1ExtremePrice:
    """Prices near 0 or 1 should be rejected (spread pushes out of bounds)."""

    def test_high_price_rejected(self):
        assert model_1_levels(_make_market(0.97)) is None

    def test_low_price_rejected(self):
        assert model_1_levels(_make_market(0.03)) is None

    def test_boundary_0_95_rejected(self):
        assert model_1_levels(_make_market(0.95)) is None


class TestModel1RiskLevels:
    """Stop-loss and take-profit values should be sane."""

    def test_stop_loss_below_entry(self):
        levels = model_1_levels(_make_market(0.50))
        assert levels.stop_loss_yes < levels.buy_yes_price
        assert levels.stop_loss_no < levels.buy_no_price

    def test_stop_loss_positive(self):
        levels = model_1_levels(_make_market(0.50))
        assert levels.stop_loss_yes > 0
        assert levels.stop_loss_no > 0

    def test_expected_profit_positive(self):
        levels = model_1_levels(_make_market(0.50))
        assert levels.expected_profit_per_share > 0

    def test_prices_within_valid_range(self):
        levels = model_1_levels(_make_market(0.50))
        for price in [
            levels.buy_yes_price, levels.sell_yes_price,
            levels.buy_no_price, levels.sell_no_price,
        ]:
            assert 0.0 < price < 1.0


# ── model_2 tests ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _enable_model_2(monkeypatch):
    """Enable model_2 feature flag for all tests in this module."""
    monkeypatch.setattr(model_2_mod, "FEATURE_FLAG", True)


class TestModel2FeatureFlag:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(model_2_mod, "FEATURE_FLAG", False)
        mkt = _make_market(0.50, price_change_5m=0.05, price_change_15m=0.08)
        assert model_2_levels(mkt) is None

    def test_enabled_with_signal_returns_levels(self):
        mkt = _make_market(0.50, price_change_5m=0.05, price_change_15m=0.08)
        assert model_2_levels(mkt) is not None


class TestModel2PositiveMomentum:
    """Positive momentum in both timeframes → YES-side trade."""

    def test_returns_yes_entry(self):
        mkt = _make_market(0.50, price_change_5m=0.05, price_change_15m=0.08)
        levels = model_2_levels(mkt)
        assert levels is not None
        assert levels.buy_yes_price > 0
        assert levels.buy_no_price == 0.0

    def test_take_profit_above_entry(self):
        mkt = _make_market(0.50, price_change_5m=0.05, price_change_15m=0.08)
        levels = model_2_levels(mkt)
        assert levels.sell_yes_price > levels.buy_yes_price

    def test_stop_loss_below_entry(self):
        mkt = _make_market(0.50, price_change_5m=0.05, price_change_15m=0.08)
        levels = model_2_levels(mkt)
        assert levels.stop_loss_yes < levels.buy_yes_price
        assert levels.stop_loss_yes > 0


class TestModel2NegativeMomentum:
    """Negative momentum in both timeframes → NO-side trade."""

    def test_returns_no_entry(self):
        mkt = _make_market(0.50, price_change_5m=-0.05, price_change_15m=-0.08)
        levels = model_2_levels(mkt)
        assert levels is not None
        assert levels.buy_no_price > 0
        assert levels.buy_yes_price == 0.0

    def test_take_profit_above_entry(self):
        mkt = _make_market(0.50, price_change_5m=-0.05, price_change_15m=-0.08)
        levels = model_2_levels(mkt)
        assert levels.sell_no_price > levels.buy_no_price

    def test_stop_loss_below_entry(self):
        mkt = _make_market(0.50, price_change_5m=-0.05, price_change_15m=-0.08)
        levels = model_2_levels(mkt)
        assert levels.stop_loss_no < levels.buy_no_price
        assert levels.stop_loss_no > 0


class TestModel2NoSignal:
    """No momentum or conflicting directions → None."""

    def test_zero_change_rejected(self):
        assert model_2_levels(_make_market(0.50)) is None

    def test_conflicting_directions_rejected(self):
        mkt = _make_market(0.50, price_change_5m=0.05, price_change_15m=-0.08)
        assert model_2_levels(mkt) is None

    def test_below_threshold_rejected(self):
        mkt = _make_market(0.50, price_change_5m=0.01, price_change_15m=0.02)
        assert model_2_levels(mkt) is None


class TestModel2PriceZone:
    """Price outside 0.25–0.75 contested zone → None."""

    def test_too_high_rejected(self):
        mkt = _make_market(0.80, price_change_5m=0.05, price_change_15m=0.08)
        assert model_2_levels(mkt) is None

    def test_too_low_rejected(self):
        mkt = _make_market(0.20, price_change_5m=0.05, price_change_15m=0.08)
        assert model_2_levels(mkt) is None

    def test_boundary_low_accepted(self):
        mkt = _make_market(0.25, price_change_5m=-0.05, price_change_15m=-0.08)
        assert model_2_levels(mkt) is not None

    def test_boundary_high_accepted(self):
        mkt = _make_market(0.75, price_change_5m=0.05, price_change_15m=0.08)
        assert model_2_levels(mkt) is not None


class TestModel2StartupCheck:
    def test_raises_when_disabled(self, monkeypatch):
        monkeypatch.setattr(model_2_mod, "FEATURE_FLAG", False)
        with pytest.raises(RuntimeError, match="FEATURE_MODEL_2"):
            model_2_mod.startup_check()

    def test_passes_when_enabled(self):
        model_2_mod.startup_check()
