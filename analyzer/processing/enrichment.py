from __future__ import annotations

from typing import Any


_MARKET_FIELDS = ("title", "slug", "event_slug")


def enrich_trades_with_market_data(
    trades: list[dict[str, Any]],
    markets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    for trade in trades:
        condition_id = trade.get("condition_id")
        if condition_id is None:
            continue

        market = markets.get(condition_id)
        if market is None:
            continue

        for field in _MARKET_FIELDS:
            if not trade.get(field) and market.get(field):
                trade[field] = market[field]

    return trades
