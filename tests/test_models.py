from models import Trade


class TestTradeCreation:
    def test_basic_creation(self):
        t = Trade(token_id="abc", price=0.5, size=10.0)
        assert t.token_id == "abc"
        assert t.price == 0.5
        assert t.size == 10.0
        assert t.side == "BUY"

    def test_side_uppercased(self):
        t = Trade(token_id="abc", price=0.5, size=10.0, side="sell")
        assert t.side == "SELL"

    def test_optional_fields_default_none(self):
        t = Trade(token_id="abc", price=0.5, size=10.0)
        assert t.market1 is None
        assert t.market2 is None
        assert t.edge is None


class TestTradeToDict:
    def test_roundtrip(self):
        t = Trade(token_id="abc", price=0.5, size=10.0, side="BUY", edge=0.05)
        d = t.to_dict()
        assert d["token_id"] == "abc"
        assert d["price"] == 0.5
        assert d["size"] == 10.0
        assert d["side"] == "BUY"
        assert d["edge"] == 0.05

    def test_includes_all_keys(self):
        t = Trade(token_id="x", price=1.0, size=1.0)
        d = t.to_dict()
        assert set(d.keys()) == {"token_id", "price", "size", "side", "market1", "market2", "edge"}


class TestTradeFromDict:
    def test_valid_dict(self):
        d = {"token_id": "abc", "price": 0.5, "size": 10}
        t = Trade.from_dict(d)
        assert t is not None
        assert t.token_id == "abc"
        assert t.price == 0.5
        assert t.size == 10.0

    def test_missing_token_id_returns_none(self):
        assert Trade.from_dict({"price": 1, "size": 1}) is None

    def test_missing_price_returns_none(self):
        assert Trade.from_dict({"token_id": "abc", "size": 1}) is None

    def test_missing_size_returns_none(self):
        assert Trade.from_dict({"token_id": "abc", "price": 1}) is None

    def test_empty_token_id_returns_none(self):
        assert Trade.from_dict({"token_id": "", "price": 1, "size": 1}) is None

    def test_invalid_price_returns_none(self):
        assert Trade.from_dict({"token_id": "abc", "price": "not_a_number", "size": 1}) is None

    def test_string_numbers_coerced(self):
        t = Trade.from_dict({"token_id": "abc", "price": "0.75", "size": "5"})
        assert t is not None
        assert t.price == 0.75
        assert t.size == 5.0

    def test_edge_parsed_when_present(self):
        t = Trade.from_dict({"token_id": "abc", "price": 1, "size": 1, "edge": 0.03})
        assert t is not None
        assert t.edge == 0.03

    def test_edge_none_when_absent(self):
        t = Trade.from_dict({"token_id": "abc", "price": 1, "size": 1})
        assert t is not None
        assert t.edge is None

    def test_side_defaults_to_buy(self):
        t = Trade.from_dict({"token_id": "abc", "price": 1, "size": 1})
        assert t is not None
        assert t.side == "BUY"
