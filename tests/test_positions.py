from unittest.mock import patch

from models import LegType, LimitOrder, OrderSide, OrderStatus
from positions import MarketPosition, PositionManager


def _make_order(
    token_id="tok_yes",
    side=OrderSide.BUY,
    leg=LegType.YES,
    price=0.43,
    size=10.0,
    status=OrderStatus.ACTIVE,
    stop_loss=0.344,
    take_profit=0.57,
):
    o = LimitOrder(
        order_id=f"paper-{token_id}",
        token_id=token_id,
        side=side,
        leg=leg,
        price=price,
        size=size,
        condition_id="cond1",
        question="Will BTC hit 100k?",
        take_profit_price=take_profit,
        stop_loss_price=stop_loss,
    )
    o.status = status
    return o


class TestMarketPosition:
    def test_is_complete_when_empty(self):
        pos = MarketPosition("c1", "Q?", "BTC")
        assert pos.is_complete

    def test_not_complete_with_active_order(self):
        pos = MarketPosition("c1", "Q?", "BTC")
        pos.entry_yes = _make_order()
        assert not pos.is_complete

    def test_complete_when_all_filled(self):
        pos = MarketPosition("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(status=OrderStatus.FILLED)
        pos.exit_yes = _make_order(side=OrderSide.SELL, status=OrderStatus.FILLED)
        assert pos.is_complete

    def test_active_orders_returns_open_only(self):
        pos = MarketPosition("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(status=OrderStatus.ACTIVE)
        pos.entry_no = _make_order(token_id="tok_no", leg=LegType.NO, status=OrderStatus.FILLED)
        assert len(pos.active_orders()) == 1


class TestPositionManager:
    def _make_manager(self, max_pos=5, max_usd=500.0):
        return PositionManager(max_pos, max_usd)

    def test_empty_manager(self):
        m = self._make_manager()
        assert m.open_count == 0
        assert m.total_exposure_usd == 0.0

    def test_create_and_has_position(self):
        m = self._make_manager()
        m.create_position("c1", "Q?", "BTC")
        assert m.has_position("c1")
        assert m.open_count == 1

    def test_can_open_respects_limit(self):
        m = self._make_manager(max_pos=1)
        m.create_position("c1", "Q?", "BTC")
        assert not m.can_open(10.0)

    def test_remove_position(self):
        m = self._make_manager()
        m.create_position("c1", "Q?", "BTC")
        m.remove_position("c1")
        assert not m.has_position("c1")

    def test_cleanup_completed(self):
        m = self._make_manager()
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(status=OrderStatus.FILLED)
        pos.exit_yes = _make_order(side=OrderSide.SELL, status=OrderStatus.FILLED)
        removed = m.cleanup_completed()
        assert removed == 1
        assert m.open_count == 0


class TestPaperFills:
    def test_buy_fills_when_price_drops(self):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)

        events = m.check_paper_fills({"tok_yes": 0.42})
        assert len(events) == 1
        assert events[0]["type"] == "fill"
        assert pos.entry_yes.status == OrderStatus.FILLED

    def test_buy_does_not_fill_above_limit(self):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)

        events = m.check_paper_fills({"tok_yes": 0.50})
        assert len(events) == 0
        assert pos.entry_yes.status == OrderStatus.ACTIVE

    def test_sell_fills_when_price_rises(self):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.exit_yes = _make_order(
            side=OrderSide.SELL, price=0.57, take_profit=0.57,
        )

        events = m.check_paper_fills({"tok_yes": 0.58})
        assert len(events) == 1
        assert pos.exit_yes.status == OrderStatus.FILLED


class TestStopLoss:
    def test_stop_triggers_below_threshold(self):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        entry = _make_order(price=0.43, stop_loss=0.344, status=OrderStatus.FILLED)
        pos.entry_yes = entry

        stops = m.check_stop_losses({"tok_yes": 0.30})
        assert len(stops) == 1
        assert stops[0]["leg"] == LegType.YES

    def test_no_stop_above_threshold(self):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        entry = _make_order(price=0.43, stop_loss=0.344, status=OrderStatus.FILLED)
        pos.entry_yes = entry

        stops = m.check_stop_losses({"tok_yes": 0.40})
        assert len(stops) == 0

    def test_no_stop_on_unfilled_entry(self):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43, stop_loss=0.344, status=OrderStatus.ACTIVE)

        stops = m.check_stop_losses({"tok_yes": 0.20})
        assert len(stops) == 0


class TestLiveFills:
    """Tests for check_live_fills() with mocked CLOB order status responses."""

    @patch("trader.get_order_status")
    def test_buy_fills_when_matched(self, mock_status):
        mock_status.return_value = {"status": "MATCHED", "filled": True, "paper": False}

        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)

        events = m.check_live_fills()

        assert len(events) == 1
        assert events[0]["type"] == "fill"
        assert events[0]["fill_price"] == 0.43
        assert events[0]["order"].side == OrderSide.BUY
        assert pos.entry_yes.status == OrderStatus.FILLED
        mock_status.assert_called_once_with("paper-tok_yes")

    @patch("trader.get_order_status")
    def test_no_fill_when_live(self, mock_status):
        mock_status.return_value = {"status": "LIVE", "filled": False, "paper": False}

        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)

        events = m.check_live_fills()

        assert len(events) == 0
        assert pos.entry_yes.status == OrderStatus.ACTIVE

    @patch("trader.get_order_status")
    def test_sell_fills_when_matched(self, mock_status):
        mock_status.return_value = {"status": "MATCHED", "filled": True, "paper": False}

        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.exit_yes = _make_order(
            side=OrderSide.SELL, price=0.57, take_profit=0.57,
        )

        events = m.check_live_fills()

        assert len(events) == 1
        assert events[0]["order"].side == OrderSide.SELL
        assert pos.exit_yes.status == OrderStatus.FILLED

    @patch("trader.get_order_status")
    def test_skips_orders_without_id(self, mock_status):
        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        order = _make_order(price=0.43)
        order.order_id = None
        pos.entry_yes = order

        events = m.check_live_fills()

        assert len(events) == 0
        mock_status.assert_not_called()

    @patch("trader.get_order_status")
    def test_unknown_status_no_fill(self, mock_status):
        mock_status.return_value = {"status": "UNKNOWN", "filled": False, "paper": False}

        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)

        events = m.check_live_fills()

        assert len(events) == 0
        assert pos.entry_yes.status == OrderStatus.ACTIVE

    @patch("trader.get_order_status")
    def test_multiple_orders_mixed_status(self, mock_status):
        def status_by_id(order_id):
            if order_id == "paper-tok_yes":
                return {"status": "MATCHED", "filled": True, "paper": False}
            return {"status": "LIVE", "filled": False, "paper": False}

        mock_status.side_effect = status_by_id

        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)
        pos.entry_no = _make_order(
            token_id="tok_no", leg=LegType.NO, price=0.55,
        )

        events = m.check_live_fills()

        assert len(events) == 1
        assert events[0]["order"].leg == LegType.YES
        assert pos.entry_yes.status == OrderStatus.FILLED
        assert pos.entry_no.status == OrderStatus.ACTIVE

    @patch("trader.get_order_status")
    def test_event_format_matches_paper_fills(self, mock_status):
        """Verify live fill events have the same keys as paper fill events."""
        mock_status.return_value = {"status": "MATCHED", "filled": True, "paper": False}

        m = PositionManager(10, 1000.0)
        pos = m.create_position("c1", "Q?", "BTC")
        pos.entry_yes = _make_order(price=0.43)

        live_events = m.check_live_fills()

        pos2 = m.create_position("c2", "Q2?", "ETH")
        pos2.entry_yes = _make_order(token_id="tok_yes2", price=0.43)
        paper_events = m.check_paper_fills({"tok_yes2": 0.40})

        assert live_events[0].keys() == paper_events[0].keys()
