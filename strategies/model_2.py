"""
Model 2 — Momentum-following on live events.

Instead of symmetric range trading, this model:
  1. Filters for active markets with recent price movement
  2. Enters directionally (BUY YES or BUY NO, not both)
  3. Follows momentum: buys the side that's been gaining
  4. Uses wider stops and targets than range trading

Based on analysis of wallet 0x507e52ef — the live sports trading
component (entry 0.30-0.60, 4-10 entries, 15-60 min hold, 65% WR).

Inputs:
  - market dict from scanner (yes_price, orderbook data)
  - price_change_5m: 5-min price change (injected by bot loop)
  - price_change_15m: 15-min price change (injected by bot loop)
  - volume_ratio: current volume vs average (injected by bot loop)

Outputs:
  - OrderLevels with directional entry (only YES or NO side active)
  - None if no momentum signal detected

Feature flags:
  - FEATURE_MODEL_2 env var must be "true" to enable
"""
from __future__ import annotations

import logging
import os
from typing import Any

from strategies import OrderLevels

log = logging.getLogger(__name__)

FEATURE_FLAG = os.getenv("FEATURE_MODEL_2", "false").lower() in ("true", "1")

# --- Momentum detection thresholds ---
MIN_PRICE_CHANGE_5M = 0.03
MIN_PRICE_CHANGE_15M = 0.05

# --- Entry zone: only trade contested markets ---
ENTRY_PRICE_LOW = 0.25
ENTRY_PRICE_HIGH = 0.75

# --- Risk management ---
TAKE_PROFIT_OFFSET = 0.12
STOP_LOSS_OFFSET = 0.08
FEE_RATE = 0.02

# --- Scaling ---
MAX_ENTRIES_PER_MARKET = 8
SCALE_IN_THRESHOLD = 0.02


def startup_check() -> None:
    """Called by load_strategy at startup. Fails fast if feature flag is off."""
    if not FEATURE_FLAG:
        raise RuntimeError(
            "Strategy 'model_2' is selected but FEATURE_MODEL_2 is not enabled. "
            "Set FEATURE_MODEL_2=true in your .env or environment, "
            "or switch to STRATEGY=model_1."
        )


def compute_levels(market: dict[str, Any]) -> OrderLevels | None:
    """Compute directional entry levels based on momentum signals.

    Returns OrderLevels for the favored side only, or None if:
    - Feature flag is disabled
    - Price is outside the contested zone (0.25-0.75)
    - No momentum signal detected
    - Expected profit is negative after fees
    """
    if not FEATURE_FLAG:
        return None

    yes_price = float(market.get("yes_price", 0))
    if not (ENTRY_PRICE_LOW <= yes_price <= ENTRY_PRICE_HIGH):
        return None

    price_change_5m = float(market.get("price_change_5m", 0))
    price_change_15m = float(market.get("price_change_15m", 0))

    signal = _detect_momentum(yes_price, price_change_5m, price_change_15m)
    if signal == 0:
        return None

    if signal > 0:
        return _build_yes_entry(market, yes_price)
    return _build_no_entry(market, yes_price)


def _detect_momentum(
    yes_price: float,
    change_5m: float,
    change_15m: float,
) -> int:
    """Detect momentum direction.

    Returns +1 (buy YES), -1 (buy NO), or 0 (no signal).

    Requires BOTH timeframes to agree on direction, and at least
    one to exceed its minimum threshold. This filters out noise
    while catching real moves.
    """
    if change_5m > 0 and change_15m > 0:
        if change_5m >= MIN_PRICE_CHANGE_5M or change_15m >= MIN_PRICE_CHANGE_15M:
            return +1
    elif change_5m < 0 and change_15m < 0:
        if abs(change_5m) >= MIN_PRICE_CHANGE_5M or abs(change_15m) >= MIN_PRICE_CHANGE_15M:
            return -1
    return 0


def _build_yes_entry(market: dict[str, Any], yes_price: float) -> OrderLevels | None:
    """Build entry levels for a YES-side momentum trade."""
    buy_price = round(yes_price, 4)
    sell_price = round(min(yes_price + TAKE_PROFIT_OFFSET, 0.95), 4)
    stop_price = round(max(yes_price - STOP_LOSS_OFFSET, 0.02), 4)

    expected_profit = (sell_price - buy_price) - FEE_RATE * (buy_price + sell_price)
    if expected_profit <= 0:
        return None

    no_price = round(1.0 - yes_price, 4)

    return OrderLevels(
        question=market.get("question", ""),
        asset=market.get("asset", ""),
        condition_id=market["condition_id"],
        yes_token_id=market["yes_token_id"],
        no_token_id=market["no_token_id"],
        mid_price=yes_price,
        half_spread=TAKE_PROFIT_OFFSET,
        volatility=0.0,
        buy_yes_price=buy_price,
        sell_yes_price=sell_price,
        buy_no_price=0.0,
        sell_no_price=0.0,
        stop_loss_yes=stop_price,
        stop_loss_no=0.0,
        expected_profit_per_share=round(expected_profit, 6),
    )


def _build_no_entry(market: dict[str, Any], yes_price: float) -> OrderLevels | None:
    """Build entry levels for a NO-side momentum trade (YES price dropping)."""
    no_price = round(1.0 - yes_price, 4)
    buy_price = round(no_price, 4)
    sell_price = round(min(no_price + TAKE_PROFIT_OFFSET, 0.95), 4)
    stop_price = round(max(no_price - STOP_LOSS_OFFSET, 0.02), 4)

    expected_profit = (sell_price - buy_price) - FEE_RATE * (buy_price + sell_price)
    if expected_profit <= 0:
        return None

    return OrderLevels(
        question=market.get("question", ""),
        asset=market.get("asset", ""),
        condition_id=market["condition_id"],
        yes_token_id=market["yes_token_id"],
        no_token_id=market["no_token_id"],
        mid_price=yes_price,
        half_spread=TAKE_PROFIT_OFFSET,
        volatility=0.0,
        buy_yes_price=0.0,
        sell_yes_price=0.0,
        buy_no_price=buy_price,
        sell_no_price=sell_price,
        stop_loss_yes=0.0,
        stop_loss_no=stop_price,
        expected_profit_per_share=round(expected_profit, 6),
    )
