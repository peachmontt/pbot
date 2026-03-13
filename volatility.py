"""
Fetch real crypto volatility from Binance public API (no auth required).

Returns the standard deviation of hourly log-returns over a configurable
window, used to adjust the range-trading spread width.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import requests

from config import BINANCE_API, BINANCE_SYMBOLS, VOLATILITY_WINDOW_HOURS

log = logging.getLogger(__name__)


def _fetch_klines(symbol: str, interval: str = "1h", limit: int = 24) -> list[list]:
    """Fetch OHLCV klines from Binance public API."""
    url = f"{BINANCE_API}/klines"
    r = requests.get(
        url,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def get_volatility(asset: str) -> Optional[float]:
    """
    Calculate recent hourly volatility for BTC, ETH, or SOL.

    Returns the standard deviation of hourly log-returns,
    or None if the asset is unknown or the API call fails.
    """
    binance_symbol = BINANCE_SYMBOLS.get(asset)
    if not binance_symbol:
        log.warning("No Binance symbol mapping for asset: %s", asset)
        return None

    try:
        klines = _fetch_klines(
            binance_symbol,
            interval="1h",
            limit=VOLATILITY_WINDOW_HOURS + 1,
        )
    except requests.RequestException as e:
        log.warning("Binance API request failed for %s: %s", asset, e)
        return None

    if len(klines) < 3:
        log.warning("Not enough kline data for %s (got %d)", asset, len(klines))
        return None

    closes = []
    for k in klines:
        try:
            closes.append(float(k[4]))
        except (IndexError, TypeError, ValueError):
            continue

    if len(closes) < 3:
        return None

    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    if len(log_returns) < 2:
        return None

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    stddev = math.sqrt(variance)

    log.debug("%s volatility: stddev=%.6f over %d hours", asset, stddev, len(log_returns))
    return stddev


def get_all_volatilities() -> dict[str, float]:
    """Fetch volatility for all configured assets. Returns {asset: stddev}."""
    result: dict[str, float] = {}
    for asset in BINANCE_SYMBOLS:
        vol = get_volatility(asset)
        if vol is not None:
            result[asset] = vol
            log.info("%s hourly volatility: %.6f", asset, vol)
        else:
            log.warning("Could not compute volatility for %s", asset)
    return result
