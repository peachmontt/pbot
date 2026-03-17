"""
Model 3 — AI-powered strategy.

Reads pre-computed signals from signal_store (populated by ai_research
worker running in a background thread) and converts them into OrderLevels
for the existing execution engine.

compute_levels() is a fast, synchronous dict lookup — no LLM calls inline.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from config import AI_ENABLED, AI_MIN_ATTENTION, AI_MIN_CONFIDENCE
from signal_store import AISignal
from strategies import OrderLevels

log = logging.getLogger(__name__)

FEE_RATE = 0.02


def startup_check() -> None:
    """Validate AI config and start the background research worker."""
    if not AI_ENABLED:
        raise RuntimeError(
            "Strategy 'model_3' requires AI_ENABLED=true in .env."
        )

    from config import AI_PROVIDER

    if AI_PROVIDER == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("AI_PROVIDER=openai but OPENAI_API_KEY is not set.")
    if AI_PROVIDER == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("AI_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")

    from ai_research import start_worker

    start_worker()
    log.info("model_3 (AI) strategy loaded — research worker started")


def compute_levels(market: dict[str, Any]) -> OrderLevels | None:
    """
    Look up a cached AI signal for this market.

    Returns OrderLevels when a fresh, high-confidence, tradeable signal
    exists whose entry zone matches the current price.  Otherwise None.
    """
    from ai_research import get_store

    cond_id = market.get("condition_id")
    if not cond_id:
        return None

    signal = get_store().get(cond_id)
    if signal is None:
        return None

    if signal.is_expired():
        return None
    if not signal.tradeable_now:
        return None
    if signal.confidence < AI_MIN_CONFIDENCE:
        return None
    if signal.attention_score < AI_MIN_ATTENTION:
        return None

    if signal.decision == "BUY_YES":
        return _build_yes_levels(market, signal)
    if signal.decision == "BUY_NO":
        return _build_no_levels(market, signal)

    return None


# ---------------------------------------------------------------------------
# Level builders
# ---------------------------------------------------------------------------

def _build_yes_levels(
    market: dict[str, Any], signal: AISignal,
) -> OrderLevels | None:
    yes_price = float(market.get("yes_price", 0))

    if not (signal.entry_min <= yes_price <= signal.entry_max):
        log.debug(
            "[AI] %s YES %.3f outside zone [%.3f, %.3f]",
            market.get("question", "")[:30], yes_price,
            signal.entry_min, signal.entry_max,
        )
        return None

    buy_price = round(yes_price, 4)
    sell_price = round(min(signal.take_profit, 0.95), 4)
    stop_price = round(max(signal.stop_loss, 0.02), 4)

    expected_profit = sell_price - buy_price - FEE_RATE * (buy_price + sell_price)
    if expected_profit <= 0:
        return None

    return OrderLevels(
        question=market.get("question", ""),
        asset=market.get("asset", ""),
        condition_id=market["condition_id"],
        yes_token_id=market["yes_token_id"],
        no_token_id=market["no_token_id"],
        mid_price=yes_price,
        half_spread=round(sell_price - buy_price, 4),
        volatility=0.0,
        buy_yes_price=buy_price,
        sell_yes_price=sell_price,
        buy_no_price=0.0,
        sell_no_price=0.0,
        stop_loss_yes=stop_price,
        stop_loss_no=0.0,
        expected_profit_per_share=round(expected_profit, 6),
    )


def _build_no_levels(
    market: dict[str, Any], signal: AISignal,
) -> OrderLevels | None:
    no_price = round(1.0 - float(market.get("yes_price", 0)), 4)

    if not (signal.entry_min <= no_price <= signal.entry_max):
        log.debug(
            "[AI] %s NO %.3f outside zone [%.3f, %.3f]",
            market.get("question", "")[:30], no_price,
            signal.entry_min, signal.entry_max,
        )
        return None

    buy_price = round(no_price, 4)
    sell_price = round(min(signal.take_profit, 0.95), 4)
    stop_price = round(max(signal.stop_loss, 0.02), 4)

    expected_profit = sell_price - buy_price - FEE_RATE * (buy_price + sell_price)
    if expected_profit <= 0:
        return None

    return OrderLevels(
        question=market.get("question", ""),
        asset=market.get("asset", ""),
        condition_id=market["condition_id"],
        yes_token_id=market["yes_token_id"],
        no_token_id=market["no_token_id"],
        mid_price=float(market.get("yes_price", 0)),
        half_spread=round(sell_price - buy_price, 4),
        volatility=0.0,
        buy_yes_price=0.0,
        sell_yes_price=0.0,
        buy_no_price=buy_price,
        sell_no_price=sell_price,
        stop_loss_yes=0.0,
        stop_loss_no=stop_price,
        expected_profit_per_share=round(expected_profit, 6),
    )
