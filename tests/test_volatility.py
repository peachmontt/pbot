from unittest.mock import MagicMock, patch

from volatility import get_volatility


def _make_klines(closes):
    """Build fake Binance kline data from a list of close prices."""
    return [
        [0, "0", "0", "0", str(c), "0", 0, "0", 0, "0", "0", "0"]
        for c in closes
    ]


class TestGetVolatility:
    @patch("volatility._fetch_klines")
    def test_returns_positive_stddev(self, mock_fetch):
        mock_fetch.return_value = _make_klines([100, 101, 99, 102, 100, 98, 103])
        vol = get_volatility("BTC")
        assert vol is not None
        assert vol > 0

    @patch("volatility._fetch_klines")
    def test_constant_prices_zero_vol(self, mock_fetch):
        mock_fetch.return_value = _make_klines([100, 100, 100, 100, 100])
        vol = get_volatility("BTC")
        assert vol is not None
        assert vol == 0.0

    @patch("volatility._fetch_klines")
    def test_high_movement_higher_vol(self, mock_fetch):
        mock_fetch.return_value = _make_klines([100, 110, 90, 120, 80])
        vol_high = get_volatility("BTC")

        mock_fetch.return_value = _make_klines([100, 101, 100, 101, 100])
        vol_low = get_volatility("BTC")

        assert vol_high is not None and vol_low is not None
        assert vol_high > vol_low

    def test_unknown_asset_returns_none(self):
        vol = get_volatility("DOGE")
        assert vol is None

    @patch("volatility._fetch_klines")
    def test_too_few_klines_returns_none(self, mock_fetch):
        mock_fetch.return_value = _make_klines([100])
        vol = get_volatility("BTC")
        assert vol is None

    @patch("volatility._fetch_klines")
    def test_api_error_returns_none(self, mock_fetch):
        import requests
        mock_fetch.side_effect = requests.RequestException("timeout")
        vol = get_volatility("BTC")
        assert vol is None
