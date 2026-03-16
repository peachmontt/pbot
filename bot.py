"""
Polymarket trading bot — main loop.

Supports two modes via STRATEGY config:
  - model_1: Symmetric range trading (BUY YES + BUY NO around mid-price)
  - model_2: Momentum following (directional BUY on one side only)

Cycle:
  1. Scan active markets, track prices for momentum detection
  2. Compute entry levels using the active strategy
  3. Place limit orders (paired or directional depending on strategy)
  4. Monitor fills → place take-profit SELL orders
  5. Monitor stop-losses → market exit on adverse move
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
    MAX_OPEN_POSITIONS,
    MAX_POSITION_USD,
    ORDER_BUDGET_USD,
    PAPER_TRADING,
    PRIVATE_KEY,
    SCAN_INTERVAL,
    STRATEGY,
)
from journal import log_event
from models import LegType, LimitOrder, OrderSide, OrderStatus
from positions import PositionManager
from price_tracker import PriceTracker
from scanner import get_markets
from strategies import OrderLevels, load_strategy
from trader import (
    cancel_order,
    get_mid_price,
    market_sell,
    place_limit_order,
    verify_connection,
)

log = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 300


def _shares_for_budget(price: float) -> float:
    """Convert a dollar budget into number of shares at the given price."""
    if price <= 0:
        return 0.0
    return round(ORDER_BUDGET_USD / price, 2)


def _place_entry_orders(
    levels: OrderLevels,
    manager: PositionManager,
) -> bool:
    """Place entry orders for a market.

    Handles both symmetric (model_1: both YES+NO) and directional
    (model_2: only the side with price > 0) entries.
    """
    cond_id = levels.condition_id

    if manager.has_position(cond_id):
        return False

    has_yes = levels.buy_yes_price > 0
    has_no = levels.buy_no_price > 0
    sides = (1 if has_yes else 0) + (1 if has_no else 0)
    cost = ORDER_BUDGET_USD * sides
    if not manager.can_open(cost):
        return False

    pos = manager.create_position(cond_id, levels.question, levels.asset)
    placed = False

    if has_yes:
        yes_size = _shares_for_budget(levels.buy_yes_price)
        yes_result = place_limit_order(
            levels.yes_token_id, levels.buy_yes_price, yes_size, "BUY",
        )
        if yes_result.get("success"):
            order = LimitOrder(
                order_id=yes_result["order_id"],
                token_id=levels.yes_token_id,
                side=OrderSide.BUY,
                leg=LegType.YES,
                price=levels.buy_yes_price,
                size=yes_size,
                condition_id=cond_id,
                question=levels.question,
                take_profit_price=levels.sell_yes_price,
                stop_loss_price=levels.stop_loss_yes,
            )
            order.status = OrderStatus.ACTIVE
            pos.entry_yes = order
            placed = True
            log_event(
                market=levels.question, asset=levels.asset,
                condition_id=cond_id, leg="YES", action="BUY_LIMIT_PLACED",
                entry_price=levels.buy_yes_price, size=yes_size,
                notes=f"tp={levels.sell_yes_price:.2f} sl={levels.stop_loss_yes:.2f}",
            )

    if has_no:
        no_size = _shares_for_budget(levels.buy_no_price)
        no_result = place_limit_order(
            levels.no_token_id, levels.buy_no_price, no_size, "BUY",
        )
        if no_result.get("success"):
            order = LimitOrder(
                order_id=no_result["order_id"],
                token_id=levels.no_token_id,
                side=OrderSide.BUY,
                leg=LegType.NO,
                price=levels.buy_no_price,
                size=no_size,
                condition_id=cond_id,
                question=levels.question,
                take_profit_price=levels.sell_no_price,
                stop_loss_price=levels.stop_loss_no,
            )
            order.status = OrderStatus.ACTIVE
            pos.entry_no = order
            placed = True
            log_event(
                market=levels.question, asset=levels.asset,
                condition_id=cond_id, leg="NO", action="BUY_LIMIT_PLACED",
                entry_price=levels.buy_no_price, size=no_size,
                notes=f"tp={levels.sell_no_price:.2f} sl={levels.stop_loss_no:.2f}",
            )

    if not placed:
        manager.remove_position(cond_id)
        return False

    if has_yes and has_no:
        log.info(
            "NEW POSITION (range): %s | YES@%.2f NO@%.2f | spread=±%.2f",
            levels.question[:45], levels.buy_yes_price, levels.buy_no_price,
            levels.half_spread,
        )
    elif has_yes:
        log.info(
            "NEW POSITION (momentum YES): %s | BUY@%.2f → TP@%.2f SL@%.2f",
            levels.question[:45], levels.buy_yes_price,
            levels.sell_yes_price, levels.stop_loss_yes,
        )
    else:
        log.info(
            "NEW POSITION (momentum NO): %s | BUY@%.2f → TP@%.2f SL@%.2f",
            levels.question[:45], levels.buy_no_price,
            levels.sell_no_price, levels.stop_loss_no,
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
    try:
        compute_levels = load_strategy(STRATEGY)
    except (ImportError, RuntimeError) as exc:
        log.error("Cannot start: %s", exc)
        sys.exit(1)
    if not PAPER_TRADING:
        if not PRIVATE_KEY:
            log.error("LIVE MODE requires PRIVATE_KEY in .env. Exiting.")
            sys.exit(1)

        conn = verify_connection()
        if not conn.get("success"):
            log.error("CLOB connection failed: %s. Exiting.", conn.get("reason"))
            sys.exit(1)

        log.warning(
            "=== LIVE MODE — real money at risk. Budget: $%.2f/trade, max %d positions ===",
            ORDER_BUDGET_USD, MAX_OPEN_POSITIONS,
        )
        for i in range(5, 0, -1):
            log.warning("Starting in %d seconds... (Ctrl+C to abort)", i)
            time.sleep(1)

    log.info(
        "Bot started (%s mode, strategy=%s). Press Ctrl+C to stop.", mode, STRATEGY,
    )

    manager = PositionManager(MAX_OPEN_POSITIONS, MAX_POSITION_USD)
    tracker = PriceTracker()
    backoff = SCAN_INTERVAL
    consecutive_errors = 0

    while True:
        try:
            # --- Step 1: Scan markets, track prices, find entries ---
            if not MAX_OPEN_POSITIONS or manager.open_count < MAX_OPEN_POSITIONS:
                markets = get_markets()
                if not markets.empty:
                    n_fetched = len(markets)
                    n_signal = 0
                    n_rejected = 0
                    n_held = 0
                    n_placed = 0

                    for _, market in markets.iterrows():
                        mkt = market.to_dict()

                        tracker.update(mkt["yes_token_id"], float(mkt["yes_price"]))

                        signals = tracker.get_momentum_signals(mkt["yes_token_id"])
                        mkt.update(signals)

                        levels = compute_levels(mkt)
                        if levels is None:
                            n_rejected += 1
                            continue

                        n_signal += 1
                        if manager.has_position(levels.condition_id):
                            n_held += 1
                            continue

                        if MAX_OPEN_POSITIONS and manager.open_count >= MAX_OPEN_POSITIONS:
                            break

                        live_mid = get_mid_price(mkt["yes_token_id"])
                        if live_mid is not None:
                            mkt["yes_price"] = live_mid
                            mkt["no_price"] = round(1.0 - live_mid, 4)
                            levels = compute_levels(mkt)
                            if levels is None:
                                n_rejected += 1
                                continue

                        if _place_entry_orders(levels, manager):
                            n_placed += 1

                    warm, tracked = tracker.warm_up_summary(15 * 60)
                    if tracked > 0 and warm == 0:
                        log.info(
                            "Tracker warming up: 0/%d tokens have 15 min of history yet",
                            tracked,
                        )

                    log.info(
                        "Cycle: %d scanned → %d signals (%d rejected) | "
                        "%d held | %d placed | %d open | tracker: %d/%d warm",
                        n_fetched, n_signal, n_rejected,
                        n_held, n_placed, manager.open_count,
                        warm, tracked,
                    )

            # --- Step 2: Monitor existing positions ---
            if manager.open_count > 0:
                current_prices = _get_current_prices(manager)
                log.info(
                    "Monitoring %d positions (%d price quotes)",
                    manager.open_count, len(current_prices),
                )

                if PAPER_TRADING:
                    fill_events = manager.check_paper_fills(current_prices)
                else:
                    fill_events = manager.check_live_fills()

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
