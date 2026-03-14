from __future__ import annotations

from typing import Any, Callable

from .positions import RoundTrip


PriceHistoryGetter = Callable[[str, int, int], list[dict[str, Any]]]


def enrich_rounds_with_mfe_mae(
    rounds: list[RoundTrip],
    price_history_getter: PriceHistoryGetter,
) -> list[RoundTrip]:
    for rt in rounds:
        if not rt.is_closed or rt.exit_time is None:
            continue

        prices = price_history_getter(rt.asset, rt.entry_time, rt.exit_time)
        if not prices:
            continue

        max_excursion = float("-inf")
        min_excursion = float("inf")

        for point in prices:
            diff = float(point["price"]) - rt.avg_entry_price
            if diff > max_excursion:
                max_excursion = diff
            if diff < min_excursion:
                min_excursion = diff

        rt.mfe = max_excursion if max_excursion != float("-inf") else None
        rt.mae = min_excursion if min_excursion != float("inf") else None

        if rt.mfe is not None and rt.mfe > 0 and rt.total_bought > 0:
            rt.edge_captured = rt.realized_pnl / (rt.mfe * rt.total_bought)
        else:
            rt.edge_captured = None

    return rounds


def rounds_to_db_dicts(wallet: str, rounds: list[RoundTrip]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for rt in rounds:
        results.append({
            "wallet": wallet,
            "condition_id": rt.condition_id,
            "outcome": rt.outcome,
            "asset": rt.asset,
            "entry_time": rt.entry_time,
            "exit_time": rt.exit_time,
            "avg_entry_price": rt.avg_entry_price,
            "avg_exit_price": rt.avg_exit_price,
            "max_size": rt.max_size,
            "total_bought": rt.total_bought,
            "total_sold": rt.total_sold,
            "num_entries": rt.num_entries,
            "num_exits": rt.num_exits,
            "realized_pnl": rt.realized_pnl,
            "hold_duration_sec": rt.hold_duration_sec,
            "is_closed": 1 if rt.is_closed else 0,
            "mfe": rt.mfe,
            "mae": rt.mae,
            "edge_captured": rt.edge_captured,
        })
    return results
