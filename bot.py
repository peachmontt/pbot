"""
Polymarket range-trading bot — main loop.

For each BTC/ETH/SOL market:
  1. Fetch volatility from Binance
  2. Compute buy/sell levels (wider spread = higher vol)
  3. Place paired limit orders: BUY YES below mid, BUY NO below mid
  4. Monitor fills → place take-profit SELL orders
  5. Monitor stop-losses → market exit if 20% adverse move
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Any

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)

from config import (
    DEFAULT_ORDER_SIZE,
    MAX_OPEN_POSITIONS,
    MAX_POSITION_USD,
    PAPER_TRADING,
    SCAN_INTERVAL,
)
from journal import log_event
from models import LegType, LimitOrder, OrderSide, OrderStatus
from positions import PositionManager
from scanner import get_markets
from strategy import OrderLevels, compute_levels
from trader import (
    cancel_order,
    get_mid_price,
    market_sell,
    place_limit_order,
)
from volatility import get_all_volatilities

log = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 300


def _place_entry_orders(
    levels: OrderLevels,
    manager: PositionManager,
) -> bool:
    """Place the paired BUY YES + BUY NO entry orders for a market."""
    cond_id = levels.condition_id
    size = DEFAULT_ORDER_SIZE

    if manager.has_position(cond_id):
        return False

    cost = (levels.buy_yes_price + levels.buy_no_price) * size
    if not manager.can_open(cost):
        return False

    pos = manager.create_position(cond_id, levels.question, levels.asset)

    yes_result = place_limit_order(
        levels.yes_token_id, levels.buy_yes_price, size, "BUY",
    )
    if yes_result.get("success"):
        order = LimitOrder(
            order_id=yes_result["order_id"],
            token_id=levels.yes_token_id,
            side=OrderSide.BUY,
            leg=LegType.YES,
            price=levels.buy_yes_price,
            size=size,
            condition_id=cond_id,
            question=levels.question,
            take_profit_price=levels.sell_yes_price,
            stop_loss_price=levels.stop_loss_yes,
        )
        order.status = OrderStatus.ACTIVE
        pos.entry_yes = order
        log_event(
            market=levels.question, asset=levels.asset,
            condition_id=cond_id, leg="YES", action="BUY_LIMIT_PLACED",
            entry_price=levels.buy_yes_price, size=size,
            notes=f"tp={levels.sell_yes_price:.2f} sl={levels.stop_loss_yes:.2f}",
        )

    no_result = place_limit_order(
        levels.no_token_id, levels.buy_no_price, size, "BUY",
    )
    if no_result.get("success"):
        order = LimitOrder(
            order_id=no_result["order_id"],
            token_id=levels.no_token_id,
            side=OrderSide.BUY,
            leg=LegType.NO,
            price=levels.buy_no_price,
            size=size,
            condition_id=cond_id,
            question=levels.question,
            take_profit_price=levels.sell_no_price,
            stop_loss_price=levels.stop_loss_no,
        )
        order.status = OrderStatus.ACTIVE
        pos.entry_no = order
        log_event(
            market=levels.question, asset=levels.asset,
            condition_id=cond_id, leg="NO", action="BUY_LIMIT_PLACED",
            entry_price=levels.buy_no_price, size=size,
            notes=f"tp={levels.sell_no_price:.2f} sl={levels.stop_loss_no:.2f}",
        )

    if not pos.entry_yes and not pos.entry_no:
        manager.remove_position(cond_id)
        return False

    log.info(
        "NEW POSITION: %s | YES-BUY@%.2f NO-BUY@%.2f | spread=±%.2f",
        levels.question[:45], levels.buy_yes_price, levels.buy_no_price,
        levels.half_spread,
    )
    return True


def _place_take_profit(
    pos_entry: LimitOrder,
    manager: PositionManager,
) -> LimitOrder | None:
    """After a BUY fills, place a SELL limit at the take-profit price."""
    result = place_limit_order(
        pos_entry.token_id,
        pos_entry.take_profit_price,
        pos_entry.size,
        "SELL",
    )
    if not result.get("success"):
        log.warning(
            "Failed to place take-profit for %s %s: %s",
            pos_entry.leg.value, pos_entry.question[:30], result.get("reason"),
        )
        return None

    exit_order = LimitOrder(
        order_id=result["order_id"],
        token_id=pos_entry.token_id,
        side=OrderSide.SELL,
        leg=pos_entry.leg,
        price=pos_entry.take_profit_price,
        size=pos_entry.size,
        condition_id=pos_entry.condition_id,
        question=pos_entry.question,
    )
    exit_order.status = OrderStatus.ACTIVE

    log.info(
        "TAKE-PROFIT placed: %s %s | entry=%.3f → sell@%.3f",
        pos_entry.leg.value, pos_entry.question[:35],
        pos_entry.price, pos_entry.take_profit_price,
    )
    log_event(
        market=pos_entry.question, asset="",
        condition_id=pos_entry.condition_id,
        leg=pos_entry.leg.value, action="SELL_LIMIT_PLACED",
        entry_price=pos_entry.price, exit_price=pos_entry.take_profit_price,
        size=pos_entry.size,
    )
    return exit_order


def _handle_stop_loss(
    stop_event: dict[str, Any],
    manager: PositionManager,
) -> None:
    """Execute a market sell for a stop-loss trigger."""
    order = stop_event["order"]
    cond_id = stop_event["condition_id"]
    leg = stop_event["leg"]

    pos = manager.get_position(cond_id)
    if not pos:
        return

    exit_order = pos.exit_yes if leg == LegType.YES else pos.exit_no
    if exit_order and exit_order.is_open and exit_order.order_id:
        cancel_order(exit_order.order_id)
        exit_order.mark_cancelled()

    result = market_sell(order.token_id, order.size)
    fill = result.get("fill_price", 0) if result.get("success") else 0
    loss = (order.price - fill) * order.size

    if result.get("success"):
        log.warning(
            "STOP-LOSS: %s %s | entry=%.3f → exit=%.3f | loss=$%.2f",
            leg.value, pos.question[:35], order.price, fill, loss,
        )
    else:
        log.error("STOP-LOSS FAILED: %s | %s", pos.question[:35], result.get("reason"))

    log_event(
        market=pos.question, asset=pos.asset,
        condition_id=cond_id, leg=leg.value, action="STOP_LOSS",
        entry_price=order.price, exit_price=fill,
        size=order.size, pnl=-loss,
        notes=f"stop_trigger={stop_event['current_price']:.3f}",
    )

    if leg == LegType.YES:
        pos.yes_stopped_out = True
    else:
        pos.no_stopped_out = True


def _get_current_prices(manager: PositionManager) -> dict[str, float]:
    """Collect current prices for all tokens we have active orders on."""
    prices: dict[str, float] = {}
    for pos in list(manager._positions.values()):
        for order in pos.all_orders():
            if order.token_id not in prices:
                mid = get_mid_price(order.token_id)
                if mid is not None:
                    prices[order.token_id] = mid
    return prices


def run_bot() -> None:
    mode = "PAPER" if PAPER_TRADING else "LIVE"
    log.info("Range-trading bot started (%s mode). Press Ctrl+C to stop.", mode)

    manager = PositionManager(MAX_OPEN_POSITIONS, MAX_POSITION_USD)
    backoff = SCAN_INTERVAL
    consecutive_errors = 0

    volatilities: dict[str, float] = {}
    vol_fetched_at = 0.0
    VOL_REFRESH_INTERVAL = 3600

    while True:
        try:
            # --- Step 1: Fetch volatility from Binance (cached for 1 hour) ---
            now = time.time()
            if not volatilities or (now - vol_fetched_at) >= VOL_REFRESH_INTERVAL:
                volatilities = get_all_volatilities()
                vol_fetched_at = now
            if not volatilities:
                log.warning("No volatility data, skipping cycle.")
                time.sleep(backoff)
                continue

            # --- Step 2: Scan and place orders for new markets only ---
            if manager.open_count < MAX_OPEN_POSITIONS:
                markets = get_markets()
                if not markets.empty:
                    new_count = 0
                    for _, market in markets.iterrows():
                        vol = volatilities.get(market["asset"])
                        if vol is None:
                            continue
                        levels = compute_levels(market.to_dict(), vol)
                        if levels and not manager.has_position(levels.condition_id):
                            if _place_entry_orders(levels, manager):
                                new_count += 1
                    if new_count:
                        log.info("Placed orders on %d new market(s).", new_count)

            # --- Step 3: Monitor existing positions ---
            if manager.open_count > 0:
                current_prices = _get_current_prices(manager)

                if PAPER_TRADING:
                    fill_events = manager.check_paper_fills(current_prices)
                    for event in fill_events:
                        order = event["order"]
                        cond_id = event["condition_id"]
                        pos = manager.get_position(cond_id)
                        if not pos:
                            continue

                        if order.side == OrderSide.BUY:
                            log.info(
                                "BUY FILLED: %s %s@%.3f (market=%.3f)",
                                order.leg.value, pos.question[:35],
                                order.price, event["fill_price"],
                            )
                            log_event(
                                market=pos.question, asset=pos.asset,
                                condition_id=cond_id, leg=order.leg.value,
                                action="BUY_FILLED",
                                entry_price=order.price, size=order.size,
                            )
                            exit_order = _place_take_profit(order, manager)
                            if order.leg == LegType.YES:
                                pos.exit_yes = exit_order
                            else:
                                pos.exit_no = exit_order

                        elif order.side == OrderSide.SELL:
                            pnl = (order.price - (
                                pos.entry_yes.price if order.leg == LegType.YES
                                else pos.entry_no.price
                            )) * order.size
                            log.info(
                                "TAKE-PROFIT FILLED: %s %s | sell@%.3f | pnl=$%.2f",
                                order.leg.value, pos.question[:35],
                                order.price, pnl,
                            )
                            entry_price = (
                                pos.entry_yes.price if order.leg == LegType.YES
                                else pos.entry_no.price
                            )
                            log_event(
                                market=pos.question, asset=pos.asset,
                                condition_id=cond_id, leg=order.leg.value,
                                action="TAKE_PROFIT_FILLED",
                                entry_price=entry_price,
                                exit_price=order.price, size=order.size,
                                pnl=pnl,
                            )

                stop_events = manager.check_stop_losses(current_prices)
                for stop in stop_events:
                    _handle_stop_loss(stop, manager)

                removed = manager.cleanup_completed()
                if removed:
                    log.info("Closed %d completed position(s).", removed)

            backoff = SCAN_INTERVAL
            consecutive_errors = 0

        except KeyboardInterrupt:
            raise
        except Exception:
            consecutive_errors += 1
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            log.exception(
                "Cycle failed (error #%d). Retrying in %ds...",
                consecutive_errors, backoff,
            )

        time.sleep(backoff)


if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
        sys.exit(0)
