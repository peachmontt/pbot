"""Tests for the PriceTracker module."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from price_tracker import PriceTracker


@pytest.fixture
def tracker() -> PriceTracker:
    return PriceTracker()


class TestUpdate:
    def test_records_price(self, tracker: PriceTracker) -> None:
        tracker.update("tok_a", 0.55)
        assert tracker.get_price("tok_a") == 0.55

    def test_overwrites_latest(self, tracker: PriceTracker) -> None:
        tracker.update("tok_a", 0.55)
        tracker.update("tok_a", 0.60)
        assert tracker.get_price("tok_a") == 0.60

    def test_tracks_multiple_tokens(self, tracker: PriceTracker) -> None:
        tracker.update("tok_a", 0.50)
        tracker.update("tok_b", 0.70)
        assert tracker.get_price("tok_a") == 0.50
        assert tracker.get_price("tok_b") == 0.70

    def test_evicts_old_data(self, tracker: PriceTracker) -> None:
        base = time.time()
        with patch("price_tracker.time.time") as mock_time:
            mock_time.return_value = base
            tracker.update("tok_a", 0.50)

            mock_time.return_value = base + 300
            tracker.update("tok_a", 0.55)

            mock_time.return_value = base + 1500
            tracker.update("tok_a", 0.60)

        assert tracker.get_price("tok_a") == 0.60
        assert tracker.tracked_count == 1


class TestGetChange:
    def test_returns_none_for_unknown_token(self, tracker: PriceTracker) -> None:
        assert tracker.get_change("unknown", 300) is None

    def test_returns_none_with_single_point(self, tracker: PriceTracker) -> None:
        tracker.update("tok_a", 0.50)
        assert tracker.get_change("tok_a", 300) is None

    def test_uses_available_history_when_short(self, tracker: PriceTracker) -> None:
        base = time.time()
        with patch("price_tracker.time.time") as mock_time:
            mock_time.return_value = base
            tracker.update("tok_a", 0.50)
            mock_time.return_value = base + 60
            tracker.update("tok_a", 0.55)

        change = tracker.get_change("tok_a", 300)
        assert change is not None
        assert abs(change - 0.05) < 1e-9

    def test_computes_positive_change(self, tracker: PriceTracker) -> None:
        base = time.time()
        with patch("price_tracker.time.time") as mock_time:
            mock_time.return_value = base
            tracker.update("tok_a", 0.50)

            mock_time.return_value = base + 300
            tracker.update("tok_a", 0.55)

            mock_time.return_value = base + 600
            tracker.update("tok_a", 0.58)

        change = tracker.get_change("tok_a", 600)
        assert change is not None
        assert abs(change - 0.08) < 1e-9

    def test_computes_negative_change(self, tracker: PriceTracker) -> None:
        base = time.time()
        with patch("price_tracker.time.time") as mock_time:
            mock_time.return_value = base
            tracker.update("tok_a", 0.60)

            mock_time.return_value = base + 300
            tracker.update("tok_a", 0.55)

        change = tracker.get_change("tok_a", 300)
        assert change is not None
        assert abs(change - (-0.05)) < 1e-9


class TestGetMomentumSignals:
    def test_returns_zeros_without_history(self, tracker: PriceTracker) -> None:
        tracker.update("tok_a", 0.50)
        signals = tracker.get_momentum_signals("tok_a")
        assert signals["price_change_5m"] == 0.0
        assert signals["price_change_15m"] == 0.0

    def test_returns_real_values_with_history(self, tracker: PriceTracker) -> None:
        base = time.time()
        with patch("price_tracker.time.time") as mock_time:
            mock_time.return_value = base
            tracker.update("tok_a", 0.40)

            mock_time.return_value = base + 5 * 60
            tracker.update("tok_a", 0.45)

            mock_time.return_value = base + 15 * 60
            tracker.update("tok_a", 0.52)

        signals = tracker.get_momentum_signals("tok_a")
        assert abs(signals["price_change_5m"] - 0.07) < 1e-9
        assert abs(signals["price_change_15m"] - 0.12) < 1e-9


class TestClear:
    def test_clears_all(self, tracker: PriceTracker) -> None:
        tracker.update("tok_a", 0.50)
        tracker.update("tok_b", 0.70)
        assert tracker.tracked_count == 2
        tracker.clear()
        assert tracker.tracked_count == 0
        assert tracker.get_price("tok_a") is None
