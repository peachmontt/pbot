"""
Range-trading strategy: compute buy/sell levels for both YES and NO tokens.

Given the current market price and asset volatility, determines where to
place limit orders and at what price to set stop-losses.

Higher volatility → wider spread → more room for oscillation.
Lower volatility  → narrower spread → more frequent fills.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import (
    FEE_RATE,
    MAX_HALF_SPREAD,
    MIN_HALF_SPREAD,
    STOP_LOSS_PCT,
    VOLATILITY_HIGH,
    VOLATILITY_LOW,
)

log = logging.getLogger(__name__)


@dataclass
class OrderLevels:
    """Buy/sell levels for both legs of a range trade on a single market."""

    question: str
    asset: str
    condition_id: str

    yes_token_id: str
    no_token_id: str

    mid_price: float
    half_spread: float
    volatility: float

    buy_yes_price: float
    sell_yes_price: float
    buy_no_price: float
    sell_no_price: float

    stop_loss_yes: float
    stop_loss_no: float

    expected_profit_per_share: float


def _interpolate_spread(volatility: float) -> float:
    """
    Map volatility to half-spread using linear interpolation.

    vol <= VOLATILITY_LOW  → MIN_HALF_SPREAD (tight, e.g. 0.06)
    vol >= VOLATILITY_HIGH → MAX_HALF_SPREAD (wide, e.g. 0.07)
    """
    if volatility <= VOLATILITY_LOW:
        return MIN_HALF_SPREAD
    if volatility >= VOLATILITY_HIGH:
        return MAX_HALF_SPREAD
    ratio = (volatility - VOLATILITY_LOW) / (VOLATILITY_HIGH - VOLATILITY_LOW)
    return MIN_HALF_SPREAD + ratio * (MAX_HALF_SPREAD - MIN_HALF_SPREAD)


def compute_levels(
    market: dict[str, Any],
    volatility: float,
) -> OrderLevels | None:
    """
    Compute order levels for a single market.

    Returns None if the market price is too extreme for range trading
    (too close to 0 or 1, where the spread would push orders out of bounds).
    """
    yes_price = float(market["yes_price"])
    no_price = float(market["no_price"])
    mid = yes_price

    half_spread = _interpolate_spread(volatility)

    buy_yes_price = round(mid - half_spread, 4)
    sell_yes_price = round(mid + half_spread, 4)

    # NO token mirrors YES: when YES is high, NO is low and vice versa.
    # buy_no fills when YES rises to sell_yes_price (NO becomes cheap)
    # sell_no fills when YES drops to buy_yes_price (NO becomes expensive)
    buy_no_price = round(1.0 - sell_yes_price, 4)
    sell_no_price = round(1.0 - buy_yes_price, 4)

    if buy_yes_price <= 0.05 or sell_yes_price >= 0.95:
        log.debug(
            "Skipping %s: prices too extreme (buy=%.2f sell=%.2f)",
            market["question"][:40], buy_yes_price, sell_yes_price,
        )
        return None

    if buy_no_price <= 0.05 or sell_no_price >= 0.95:
        log.debug(
            "Skipping %s: NO prices too extreme (buy=%.2f sell=%.2f)",
            market["question"][:40], buy_no_price, sell_no_price,
        )
        return None

    stop_loss_yes = round(buy_yes_price * (1.0 - STOP_LOSS_PCT), 4)
    stop_loss_no = round(buy_no_price * (1.0 - STOP_LOSS_PCT), 4)

    spread_total = sell_yes_price - buy_yes_price
    fees = FEE_RATE * (buy_yes_price + sell_yes_price)
    expected_profit = round(spread_total - fees, 6)

    log.debug(
        "%s | mid=%.2f vol=%.5f spread=±%.2f → BUY YES@%.2f SELL@%.2f | "
        "BUY NO@%.2f SELL@%.2f | profit/share=$%.4f",
        market["question"][:35], mid, volatility, half_spread,
        buy_yes_price, sell_yes_price,
        buy_no_price, sell_no_price,
        expected_profit,
    )

    return OrderLevels(
        question=market["question"],
        asset=market["asset"],
        condition_id=market["condition_id"],
        yes_token_id=market["yes_token_id"],
        no_token_id=market["no_token_id"],
        mid_price=mid,
        half_spread=half_spread,
        volatility=volatility,
        buy_yes_price=buy_yes_price,
        sell_yes_price=sell_yes_price,
        buy_no_price=buy_no_price,
        sell_no_price=sell_no_price,
        stop_loss_yes=stop_loss_yes,
        stop_loss_no=stop_loss_no,
        expected_profit_per_share=expected_profit,
    )
