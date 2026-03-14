import json
from unittest.mock import MagicMock, patch

from scanner import _parse_array_maybe_json, get_markets


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


def _make_gamma_market(
    question="Will BTC hit 100k?",
    outcomes=None,
    prices=None,
    token_ids=None,
    condition_id="cond123",
):
    return {
        "question": question,
        "outcomes": json.dumps(outcomes or ["Yes", "No"]),
        "outcomePrices": json.dumps(prices or ["0.65", "0.35"]),
        "clobTokenIds": json.dumps(token_ids or ["tok_yes", "tok_no"]),
        "conditionId": condition_id,
        "slug": "btc-100k",
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
    def test_accepts_any_topic(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_gamma_market(question="Will DOGE hit $1?"),
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert len(df) == 1

    @patch("scanner.requests.get")
    def test_skips_bad_data(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_gamma_market(outcomes=["Yes"]),
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty

    @patch("scanner.requests.get")
    def test_skips_missing_token_ids(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_gamma_market(token_ids=["tok_yes"]),
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty

    @patch("scanner.requests.get")
    def test_deduplicates_by_condition_id(self, mock_get):
        m = _make_gamma_market()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [m, m]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert len(df) == 1

    @patch("scanner.requests.get")
    def test_returns_empty_df_on_no_data(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        df = get_markets()
        assert df.empty

    @patch("scanner.requests.get")
    def test_paginates_multiple_pages(self, mock_get):
        page1 = [_make_gamma_market(condition_id=f"c{i}") for i in range(500)]
        page2 = [_make_gamma_market(condition_id=f"c{i}") for i in range(500, 510)]

        responses = []
        for data in [page1, page2]:
            resp = MagicMock()
            resp.json.return_value = data
            resp.raise_for_status = MagicMock()
            responses.append(resp)

        mock_get.side_effect = responses
        df = get_markets()
        assert len(df) == 510

    @patch("scanner.requests.get")
    def test_stops_pagination_on_short_page(self, mock_get):
        page1 = [_make_gamma_market(condition_id=f"c{i}") for i in range(100)]

        resp = MagicMock()
        resp.json.return_value = page1
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        df = get_markets()
        assert len(df) == 100
        assert mock_get.call_count == 1

    @patch("scanner.requests.get")
    def test_handles_api_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("timeout")

        df = get_markets()
        assert df.empty
