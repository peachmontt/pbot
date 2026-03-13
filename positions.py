"""
Order lifecycle manager for the range-trading strategy.

Tracks paired YES/NO limit orders per market, detects fills (paper or live),
triggers stop-losses, and manages the buy → sell → exit cycle.
"""
from __future__ import annotations

import logging
from typing import Any

from config import PAPER_TRADING, STOP_LOSS_PCT
from models import LegType, LimitOrder, OrderSide, OrderStatus

log = logging.getLogger(__name__)


class MarketPosition:
    """
    Tracks all orders for a single Polymarket market (condition_id).

    Lifecycle per leg (YES or NO):
      1. BUY limit placed  (entry_order)
      2. BUY fills          → place SELL limit (exit_order)
      3. SELL fills          → leg is complete, profit taken
      OR
      2b. Price drops 20%   → market sell (stop-loss)
    """

    def __init__(self, condition_id: str, question: str, asset: str) -> None:
        self.condition_id = condition_id
        self.question = question
        self.asset = asset

        self.entry_yes: LimitOrder | None = None
        self.entry_no: LimitOrder | None = None
        self.exit_yes: LimitOrder | None = None
        self.exit_no: LimitOrder | None = None

        self.yes_stopped_out = False
        self.no_stopped_out = False

    @property
    def is_complete(self) -> bool:
        """True when no more orders are active or pending for this market."""
        for order in (self.entry_yes, self.entry_no, self.exit_yes, self.exit_no):
            if order is not None and order.is_open:
                return False
        return True

    @property
    def has_filled_entries(self) -> bool:
        yes_filled = self.entry_yes is not None and self.entry_yes.status == OrderStatus.FILLED
        no_filled = self.entry_no is not None and self.entry_no.status == OrderStatus.FILLED
        return yes_filled or no_filled

    def active_orders(self) -> list[LimitOrder]:
        return [
            o for o in (self.entry_yes, self.entry_no, self.exit_yes, self.exit_no)
            if o is not None and o.is_open
        ]

    def all_orders(self) -> list[LimitOrder]:
        return [
            o for o in (self.entry_yes, self.entry_no, self.exit_yes, self.exit_no)
            if o is not None
        ]

    def summary_line(self) -> str:
        parts = [f"  {self.question[:50]}"]
        for label, order in [("E-YES", self.entry_yes), ("E-NO", self.entry_no),
                             ("X-YES", self.exit_yes), ("X-NO", self.exit_no)]:
            if order:
                parts.append(f"{label}:{order.status.value}@{order.price:.2f}")
        if self.yes_stopped_out:
            parts.append("YES-STOPPED")
        if self.no_stopped_out:
            parts.append("NO-STOPPED")
        return " | ".join(parts)


class PositionManager:
    """
    Manages all market positions and enforces risk limits.

    In paper mode, simulates fills by comparing current prices to order prices.
    In live mode, checks order status via the CLOB API.
    """

    def __init__(self, max_positions: int, max_exposure_usd: float) -> None:
        self.max_positions = max_positions
        self.max_exposure_usd = max_exposure_usd
        self._positions: dict[str, MarketPosition] = {}

    @property
    def open_count(self) -> int:
        return len(self._positions)

    @property
    def total_exposure_usd(self) -> float:
        total = 0.0
        for pos in self._positions.values():
            for order in pos.all_orders():
                if order.status in (OrderStatus.ACTIVE, OrderStatus.FILLED):
                    total += order.notional_usd
        return total

    def has_position(self, condition_id: str) -> bool:
        return condition_id in self._positions

    def can_open(self, cost_usd: float) -> bool:
        if self.open_count >= self.max_positions:
            log.warning("Position limit reached (%d/%d)", self.open_count, self.max_positions)
            return False
        if self.total_exposure_usd + cost_usd > self.max_exposure_usd:
            log.warning(
                "Exposure limit: $%.2f + $%.2f > $%.2f",
                self.total_exposure_usd, cost_usd, self.max_exposure_usd,
            )
            return False
        return True

    def create_position(
        self, condition_id: str, question: str, asset: str,
    ) -> MarketPosition:
        pos = MarketPosition(condition_id, question, asset)
        self._positions[condition_id] = pos
        return pos

    def get_position(self, condition_id: str) -> MarketPosition | None:
        return self._positions.get(condition_id)

    def remove_position(self, condition_id: str) -> None:
        self._positions.pop(condition_id, None)

    def check_paper_fills(
        self,
        current_prices: dict[str, float],
    ) -> list[dict[str, Any]]:
        """
        Paper mode: simulate fills by comparing current token prices to order prices.

        current_prices: {token_id: current_price}

        Returns a list of events: [{"type": "fill"|"stop_loss", "order": LimitOrder, ...}]
        """
        events: list[dict[str, Any]] = []

        for pos in list(self._positions.values()):
            for order in pos.active_orders():
                current = current_prices.get(order.token_id)
                if current is None:
                    continue

                if order.side == OrderSide.BUY and current <= order.price:
                    order.mark_filled(current)
                    events.append({
                        "type": "fill",
                        "order": order,
                        "condition_id": pos.condition_id,
                        "fill_price": current,
                    })
                    log.info(
                        "[PAPER FILL] BUY %s %s@%.3f (current=%.3f)",
                        order.leg.value, pos.question[:30], order.price, current,
                    )

                elif order.side == OrderSide.SELL and current >= order.price:
                    order.mark_filled(current)
                    events.append({
                        "type": "fill",
                        "order": order,
                        "condition_id": pos.condition_id,
                        "fill_price": current,
                    })
                    log.info(
                        "[PAPER FILL] SELL %s %s@%.3f (current=%.3f)",
                        order.leg.value, pos.question[:30], order.price, current,
                    )

        return events

    def check_stop_losses(
        self,
        current_prices: dict[str, float],
    ) -> list[dict[str, Any]]:
        """
        Check if any filled entry positions have breached their stop-loss.

        Returns list of orders that need market-sell execution.
        """
        stops: list[dict[str, Any]] = []

        for pos in list(self._positions.values()):
            if pos.entry_yes and pos.entry_yes.status == OrderStatus.FILLED:
                if not pos.yes_stopped_out and not (
                    pos.exit_yes and pos.exit_yes.status == OrderStatus.FILLED
                ):
                    current = current_prices.get(pos.entry_yes.token_id)
                    if current is not None and current <= pos.entry_yes.stop_loss_price:
                        stops.append({
                            "type": "stop_loss",
                            "leg": LegType.YES,
                            "order": pos.entry_yes,
                            "condition_id": pos.condition_id,
                            "current_price": current,
                            "stop_price": pos.entry_yes.stop_loss_price,
                        })
                        log.warning(
                            "STOP-LOSS YES %s: current=%.3f <= stop=%.3f",
                            pos.question[:30], current, pos.entry_yes.stop_loss_price,
                        )

            if pos.entry_no and pos.entry_no.status == OrderStatus.FILLED:
                if not pos.no_stopped_out and not (
                    pos.exit_no and pos.exit_no.status == OrderStatus.FILLED
                ):
                    current = current_prices.get(pos.entry_no.token_id)
                    if current is not None and current <= pos.entry_no.stop_loss_price:
                        stops.append({
                            "type": "stop_loss",
                            "leg": LegType.NO,
                            "order": pos.entry_no,
                            "condition_id": pos.condition_id,
                            "current_price": current,
                            "stop_price": pos.entry_no.stop_loss_price,
                        })
                        log.warning(
                            "STOP-LOSS NO %s: current=%.3f <= stop=%.3f",
                            pos.question[:30], current, pos.entry_no.stop_loss_price,
                        )

        return stops

    def cleanup_completed(self) -> int:
        """Remove positions where all legs are done. Returns count removed."""
        to_remove = [cid for cid, pos in self._positions.items() if pos.is_complete]
        for cid in to_remove:
            pos = self._positions.pop(cid)
            log.info("Position complete, removed: %s", pos.question[:50])
        return len(to_remove)

    def summary(self) -> str:
        lines = [
            f"Positions: {self.open_count}/{self.max_positions} "
            f"| Exposure: ${self.total_exposure_usd:.2f}/${self.max_exposure_usd:.2f}"
        ]
        for pos in self._positions.values():
            lines.append(pos.summary_line())
        return "\n".join(lines)
