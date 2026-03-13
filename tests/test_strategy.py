from unittest.mock import patch

from strategy import OrderLevels, _interpolate_spread, compute_levels


class TestInterpolateSpread:
    def _patch(self):
        return patch.multiple(
            "strategy",
            VOLATILITY_LOW=0.005,
            VOLATILITY_HIGH=0.025,
            MIN_HALF_SPREAD=0.06,
            MAX_HALF_SPREAD=0.07,
        )

    def test_low_vol_returns_min_spread(self):
        with self._patch():
            assert _interpolate_spread(0.001) == 0.06

    def test_high_vol_returns_max_spread(self):
        with self._patch():
            assert _interpolate_spread(0.03) == 0.07

    def test_mid_vol_interpolates(self):
        with self._patch():
            spread = _interpolate_spread(0.015)
            assert 0.06 < spread < 0.07

    def test_exact_low_boundary(self):
        with self._patch():
            assert _interpolate_spread(0.005) == 0.06

    def test_exact_high_boundary(self):
        with self._patch():
            assert _interpolate_spread(0.025) == 0.07


class TestComputeLevels:
    def _market(self, yes_price=0.50, no_price=0.50):
        return {
            "question": "Will BTC hit 100k?",
            "asset": "BTC",
            "condition_id": "cond1",
            "yes_token_id": "yes_tok",
            "no_token_id": "no_tok",
            "yes_price": yes_price,
            "no_price": no_price,
        }

    def _patch(self):
        return patch.multiple(
            "strategy",
            VOLATILITY_LOW=0.005,
            VOLATILITY_HIGH=0.025,
            MIN_HALF_SPREAD=0.06,
            MAX_HALF_SPREAD=0.07,
            STOP_LOSS_PCT=0.20,
            FEE_RATE=0.02,
        )

    def test_returns_order_levels_for_normal_market(self):
        with self._patch():
            levels = compute_levels(self._market(), volatility=0.01)
        assert levels is not None
        assert isinstance(levels, OrderLevels)

    def test_buy_yes_below_mid(self):
        with self._patch():
            levels = compute_levels(self._market(0.50, 0.50), volatility=0.025)
        assert levels is not None
        assert levels.buy_yes_price < 0.50
        assert levels.buy_yes_price == 0.43

    def test_sell_yes_above_mid(self):
        with self._patch():
            levels = compute_levels(self._market(0.50, 0.50), volatility=0.025)
        assert levels is not None
        assert levels.sell_yes_price > 0.50
        assert levels.sell_yes_price == 0.57

    def test_no_prices_mirror_yes(self):
        with self._patch():
            levels = compute_levels(self._market(0.50, 0.50), volatility=0.025)
        assert levels is not None
        assert levels.buy_no_price == round(1.0 - levels.sell_yes_price, 4)
        assert levels.sell_no_price == round(1.0 - levels.buy_yes_price, 4)

    def test_stop_loss_set_correctly(self):
        with self._patch():
            levels = compute_levels(self._market(0.50, 0.50), volatility=0.025)
        assert levels is not None
        assert levels.stop_loss_yes == round(0.43 * 0.80, 4)

    def test_extreme_price_returns_none(self):
        with self._patch():
            levels = compute_levels(self._market(0.03, 0.97), volatility=0.01)
        assert levels is None

    def test_expected_profit_positive(self):
        with self._patch():
            levels = compute_levels(self._market(0.50, 0.50), volatility=0.025)
        assert levels is not None
        assert levels.expected_profit_per_share > 0

    def test_higher_vol_wider_spread(self):
        with self._patch():
            levels_low = compute_levels(self._market(), volatility=0.005)
            levels_high = compute_levels(self._market(), volatility=0.025)
        assert levels_low is not None and levels_high is not None
        assert levels_high.half_spread >= levels_low.half_spread
