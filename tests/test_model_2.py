from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from strategies.model_2 import (
    ENTRY_PRICE_HIGH,
    ENTRY_PRICE_LOW,
    MIN_PRICE_CHANGE_5M,
    STOP_LOSS_OFFSET,
    TAKE_PROFIT_OFFSET,
    _detect_momentum,
    compute_levels,
)


def _make_market(
    yes_price: float = 0.50,
    price_change_5m: float = 0.0,
    price_change_15m: float = 0.0,
) -> dict:
    return {
        "question": "Will X win?",
        "asset": "test-asset",
        "condition_id": "cond-1",
        "yes_token_id": "tok-yes",
        "no_token_id": "tok-no",
        "yes_price": yes_price,
        "price_change_5m": price_change_5m,
        "price_change_15m": price_change_15m,
    }


class TestDetectMomentum:
    def test_no_signal_on_zero_change(self):
        assert _detect_momentum(0.5, 0.0, 0.0) == 0

    def test_positive_signal_when_both_up(self):
        assert _detect_momentum(0.5, 0.04, 0.06) == +1

    def test_negative_signal_when_both_down(self):
        assert _detect_momentum(0.5, -0.04, -0.06) == -1

    def test_no_signal_when_directions_disagree(self):
        assert _detect_momentum(0.5, 0.04, -0.06) == 0
        assert _detect_momentum(0.5, -0.04, 0.06) == 0

    def test_no_signal_when_below_threshold(self):
        assert _detect_momentum(0.5, 0.01, 0.02) == 0

    def test_signal_when_5m_exceeds_threshold(self):
        assert _detect_momentum(0.5, MIN_PRICE_CHANGE_5M, 0.01) == +1

    def test_signal_when_15m_exceeds_threshold(self):
        assert _detect_momentum(0.5, 0.01, 0.05) == +1


@patch.dict(os.environ, {"FEATURE_MODEL_2": "true"})
class TestComputeLevels:
    def setup_method(self):
        import strategies.model_2 as m
        m.FEATURE_FLAG = True

    def test_returns_none_without_momentum(self):
        market = _make_market(yes_price=0.50)
        assert compute_levels(market) is None

    def test_returns_none_for_extreme_price(self):
        market = _make_market(yes_price=0.10, price_change_5m=0.05, price_change_15m=0.06)
        assert compute_levels(market) is None

    def test_returns_none_for_high_price(self):
        market = _make_market(yes_price=0.90, price_change_5m=0.05, price_change_15m=0.06)
        assert compute_levels(market) is None

    def test_yes_entry_on_positive_momentum(self):
        market = _make_market(yes_price=0.45, price_change_5m=0.04, price_change_15m=0.06)
        levels = compute_levels(market)

        assert levels is not None
        assert levels.buy_yes_price == 0.45
        assert levels.sell_yes_price == round(0.45 + TAKE_PROFIT_OFFSET, 4)
        assert levels.stop_loss_yes == round(0.45 - STOP_LOSS_OFFSET, 4)
        assert levels.buy_no_price == 0.0
        assert levels.sell_no_price == 0.0

    def test_no_entry_on_negative_momentum(self):
        market = _make_market(yes_price=0.55, price_change_5m=-0.04, price_change_15m=-0.06)
        levels = compute_levels(market)

        assert levels is not None
        assert levels.buy_no_price == round(1.0 - 0.55, 4)
        assert levels.sell_no_price == round(1.0 - 0.55 + TAKE_PROFIT_OFFSET, 4)
        assert levels.buy_yes_price == 0.0

    def test_expected_profit_is_positive(self):
        market = _make_market(yes_price=0.50, price_change_5m=0.04, price_change_15m=0.06)
        levels = compute_levels(market)

        assert levels is not None
        assert levels.expected_profit_per_share > 0

    def test_stop_loss_respects_floor(self):
        market = _make_market(yes_price=0.28, price_change_5m=0.04, price_change_15m=0.06)
        levels = compute_levels(market)

        assert levels is not None
        assert levels.stop_loss_yes >= 0.02

    def test_take_profit_respects_ceiling(self):
        market = _make_market(yes_price=0.74, price_change_5m=0.04, price_change_15m=0.06)
        levels = compute_levels(market)

        assert levels is not None
        assert levels.sell_yes_price <= 0.95

    def test_feature_flag_disabled(self):
        import strategies.model_2 as m
        m.FEATURE_FLAG = False
        market = _make_market(yes_price=0.50, price_change_5m=0.04, price_change_15m=0.06)
        assert compute_levels(market) is None
        m.FEATURE_FLAG = True
