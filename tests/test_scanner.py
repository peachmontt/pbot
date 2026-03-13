import json
from unittest.mock import MagicMock, patch

from scanner import _parse_array_maybe_json, detect_asset, get_markets


class TestParseArrayMaybeJson:
    def test_none_returns_none(self):
        assert _parse_array_maybe_json(None) is None

    def test_list_passthrough(self):
        assert _parse_array_maybe_json([1, 2]) == [1, 2]

    def test_json_string_parsed(self):
        assert _parse_array_maybe_json('["a","b"]') == ["a", "b"]

    def test_non_array_json_returns_none(self):
        assert _parse_array_maybe_json('{"key": "val"}') is None

    def test_invalid_json_returns_none(self):
        assert _parse_array_maybe_json("not json") is None

    def test_int_returns_none(self):
        assert _parse_array_maybe_json(42) is None


class TestDetectAsset:
    def test_detects_btc(self):
        assert detect_asset("Will BTC hit 100k?") == "BTC"

    def test_detects_bitcoin_full_name(self):
        assert detect_asset("Will Bitcoin reach 100k?") == "BTC"

    def test_detects_eth(self):
        assert detect_asset("ETH above 5000?") == "ETH"

    def test_detects_sol(self):
        assert detect_asset("SOL to $200?") == "SOL"

    def test_case_insensitive(self):
        assert detect_asset("btc price") == "BTC"

    def test_no_match_returns_none(self):
        assert detect_asset("Will DOGE moon?") is None


def _make_gamma_market(
    question="Will BTC hit 100k?",
    outcomes=None,
    prices=None,
    token_ids=None,
    condition_id="cond123",
    volume=5000.0,
    end_date="2027-06-01T00:00:00Z",
):
    return {
        "question": question,
        "outcomes": json.dumps(outcomes or ["Yes", "No"]),
        "outcomePrices": json.dumps(prices or ["0.65", "0.35"]),
        "clobTokenIds": json.dumps(token_ids or ["tok_yes", "tok_no"]),
        "conditionId": condition_id,
        "slug": "btc-100k",
        "volume24hr": volume,
        "endDate": end_date,
    }


class TestGetMarkets:
    @patch("scanner.requests.get")
    def test_parses_valid_market(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [_make_gamma_market()]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert len(df) == 1
        assert df.iloc[0]["yes_price"] == 0.65
        assert df.iloc[0]["no_price"] == 0.35

    @patch("scanner.requests.get")
    def test_filters_non_crypto(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_gamma_market(question="Will DOGE hit $1?"),
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty

    @patch("scanner.requests.get")
    def test_filters_low_volume(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_gamma_market(volume=10.0),
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty

    @patch("scanner.requests.get")
    def test_filters_near_expiry(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_gamma_market(end_date="2026-03-14T00:00:00Z"),
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty

    @patch("scanner.requests.get")
    def test_includes_volume_and_expiry_columns(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [_make_gamma_market()]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert "volume_24h" in df.columns
        assert "days_to_expiry" in df.columns

    @patch("scanner.requests.get")
    def test_returns_empty_df_on_no_data(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty
