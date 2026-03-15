from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from analyzer.api.client import PolymarketClient

logger = logging.getLogger(__name__)

# CLOB API enforces max range per fidelity level.
# 7 days with fidelity=5 gives ~2016 data points per window — plenty for MFE/MAE.
_WINDOW_SECONDS = 7 * 24 * 60 * 60
_FIDELITY = 5


async def fetch_price_history(
    client: PolymarketClient,
    asset_id: str,
    start_ts: int,
    end_ts: int,
) -> list[dict]:
    """Fetch price history from the CLOB API, splitting into weekly windows.

    Returns list of {t: timestamp, p: price} dicts.
    """
    all_points: list[dict] = []
    window_start = start_ts

    while window_start < end_ts:
        window_end = min(window_start + _WINDOW_SECONDS, end_ts)

        data, error = await client.get(
            "/prices-history",
            params={
                "market": asset_id,
                "startTs": window_start,
                "endTs": window_end,
                "fidelity": _FIDELITY,
            },
        )

        if error is not None:
            logger.debug("No price history for asset %s (window %d-%d)", asset_id, window_start, window_end)
            window_start = window_end
            continue

        if isinstance(data, dict):
            history = data.get("history")
            if isinstance(history, list):
                all_points.extend(history)
        elif isinstance(data, list):
            all_points.extend(data)

        window_start = window_end

    return all_points


async def fetch_prices_batch(
    client: PolymarketClient,
    assets: list[str],
    start_ts: int,
    end_ts: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, list[dict]]:
    """Fetch price history for many assets concurrently.

    Uses the client's built-in semaphore and throttle for rate-limiting.
    Returns {asset_id: [price_points]} for assets that had data.
    """
    results: dict[str, list[dict]] = {}
    completed = 0
    total = len(assets)
    lock = asyncio.Lock()

    async def _fetch_one(asset_id: str) -> None:
        nonlocal completed
        points = await fetch_price_history(client, asset_id, start_ts, end_ts)
        async with lock:
            if points:
                results[asset_id] = points
            completed += 1
            if on_progress is not None:
                on_progress(completed, total)

    batch_size = 50
    for i in range(0, total, batch_size):
        batch = assets[i : i + batch_size]
        await asyncio.gather(*[_fetch_one(a) for a in batch])

    return results


def _merge_asset_windows(
    windows: list[tuple[str, int, int]],
) -> dict[str, tuple[int, int]]:
    """Merge per-round (asset, start, end) into one (min_start, max_end) per asset."""
    merged: dict[str, tuple[int, int]] = {}
    for asset, start, end in windows:
        if asset in merged:
            prev_start, prev_end = merged[asset]
            merged[asset] = (min(prev_start, start), max(prev_end, end))
        else:
            merged[asset] = (start, end)
    return merged


async def fetch_prices_for_rounds(
    client: PolymarketClient,
    round_windows: list[tuple[str, int, int]],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, list[dict]]:
    """Fetch price history only for the time windows needed by closed rounds.

    Merges overlapping windows per asset, then fetches concurrently.
    Returns {asset_id: [price_points]}.
    """
    merged = _merge_asset_windows(round_windows)
    if not merged:
        return {}

    results: dict[str, list[dict]] = {}
    completed = 0
    total = len(merged)
    lock = asyncio.Lock()

    async def _fetch_one(asset_id: str, start_ts: int, end_ts: int) -> None:
        nonlocal completed
        points = await fetch_price_history(client, asset_id, start_ts, end_ts)
        async with lock:
            if points:
                results[asset_id] = points
            completed += 1
            if on_progress is not None:
                on_progress(completed, total)

    items = list(merged.items())
    batch_size = 50
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        await asyncio.gather(*[_fetch_one(a, s, e) for a, (s, e) in batch])

    return results
