"""
Model 1 — Fixed-spread range trading.

Places symmetric BUY/SELL limit orders around the current YES mid-price.
The spread is interpolated from a volatility parameter (default: fixed).

Suitable for markets where the price oscillates around a stable level.
"""
from __future__ import annotations

import logging
from typing import Any

from strategies import OrderLevels

log = logging.getLogger(__name__)

# --- Model parameters (self-contained) ---
MIN_HALF_SPREAD = 0.06
MAX_HALF_SPREAD = 0.07
VOLATILITY_LOW = 0.005
VOLATILITY_HIGH = 0.025
DEFAULT_VOLATILITY = 0.015
STOP_LOSS_PCT = 0.20
FEE_RATE = 0.02


def _interpolate_spread(volatility: float) -> float:
    if volatility <= VOLATILITY_LOW:
        return MIN_HALF_SPREAD
    if volatility >= VOLATILITY_HIGH:
        return MAX_HALF_SPREAD
    ratio = (volatility - VOLATILITY_LOW) / (VOLATILITY_HIGH - VOLATILITY_LOW)
    return MIN_HALF_SPREAD + ratio * (MAX_HALF_SPREAD - MIN_HALF_SPREAD)


def compute_levels(market: dict[str, Any]) -> OrderLevels | None:
    """
    Compute order levels for a single market.

    Returns None if the market price is too extreme for range trading
    (too close to 0 or 1, where the spread would push orders out of bounds).
    """
    yes_price = float(market["yes_price"])
    mid = yes_price

    half_spread = _interpolate_spread(DEFAULT_VOLATILITY)

    buy_yes_price = round(mid - half_spread, 4)
    sell_yes_price = round(mid + half_spread, 4)

    buy_no_price = round(1.0 - sell_yes_price, 4)
    sell_no_price = round(1.0 - buy_yes_price, 4)

    if buy_yes_price <= 0.05 or sell_yes_price >= 0.95:
        return None
    if buy_no_price <= 0.05 or sell_no_price >= 0.95:
        return None

    stop_loss_yes = round(buy_yes_price * (1.0 - STOP_LOSS_PCT), 4)
    stop_loss_no = round(buy_no_price * (1.0 - STOP_LOSS_PCT), 4)

    spread_total = sell_yes_price - buy_yes_price
    fees = FEE_RATE * (buy_yes_price + sell_yes_price)
    expected_profit = round(spread_total - fees, 6)

    return OrderLevels(
        question=market["question"],
        asset=market.get("asset", ""),
        condition_id=market["condition_id"],
        yes_token_id=market["yes_token_id"],
        no_token_id=market["no_token_id"],
        mid_price=mid,
        half_spread=half_spread,
        volatility=DEFAULT_VOLATILITY,
        buy_yes_price=buy_yes_price,
        sell_yes_price=sell_yes_price,
        buy_no_price=buy_no_price,
        sell_no_price=sell_no_price,
        stop_loss_yes=stop_loss_yes,
        stop_loss_no=stop_loss_no,
        expected_profit_per_share=expected_profit,
    )
