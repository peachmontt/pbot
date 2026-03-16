"""
Strategy plugin system.

Each strategy module must export:
    compute_levels(market: dict) -> OrderLevels | None

Select the active strategy in config.py via STRATEGY = "model_1".
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Callable

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


ComputeLevelsFn = Callable[[dict[str, Any]], OrderLevels | None]


def load_strategy(name: str) -> ComputeLevelsFn:
    """
    Import strategies.<name> and return its compute_levels function.

    Raises ImportError if the module or function is missing.
    Raises RuntimeError if the strategy's startup_check() fails
    (e.g. required feature flag is off).
    """
    module = importlib.import_module(f"strategies.{name}")
    fn = getattr(module, "compute_levels", None)
    if fn is None:
        raise ImportError(f"Strategy 'strategies.{name}' has no compute_levels function")

    startup_check = getattr(module, "startup_check", None)
    if startup_check is not None:
        startup_check()

    log.info("Loaded strategy: %s", name)
    return fn
