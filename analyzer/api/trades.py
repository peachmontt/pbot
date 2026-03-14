from __future__ import annotations

import logging

from analyzer.api.client import PolymarketClient

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 500
_MAX_OFFSET = 3000
_DAY_SECONDS = 24 * 60 * 60


def _daily_windows(start_ts: int, end_ts: int) -> list[tuple[int, int]]:
    """Split a timestamp range into non-overlapping daily windows."""
    windows: list[tuple[int, int]] = []
    current = start_ts
    while current < end_ts:
        window_end = min(current + _DAY_SECONDS, end_ts)
        windows.append((current, window_end))
        current = window_end
    return windows


async def _fetch_trades_window(
    client: PolymarketClient,
    wallet: str,
    start_ts: int,
    end_ts: int,
) -> list[dict]:
    """Fetch all TRADE activity pages within a single time window."""
    results: list[dict] = []
    offset = 0

    while offset <= _MAX_OFFSET:
        data, error = await client.get(
            "/activity",
            params={
                "user": wallet,
                "type": "TRADE",
                "start": start_ts,
                "end": end_ts,
                "limit": _PAGE_LIMIT,
                "offset": offset,
                "sortBy": "TIMESTAMP",
                "sortDirection": "ASC",
            },
        )
        if error is not None:
            logger.error(
                "Failed to fetch trades for %s (offset=%d, window=%d-%d): %s",
                wallet, offset, start_ts, end_ts, error,
            )
            break

        if not isinstance(data, list) or len(data) == 0:
            break

        results.extend(data)

        if len(data) < _PAGE_LIMIT:
            break

        offset += _PAGE_LIMIT

    return results


async def fetch_all_trades(
    client: PolymarketClient, wallet: str, start_ts: int, end_ts: int,
) -> list[dict]:
    """Fetch all trades for a wallet using weekly time windows to bypass offset limits."""
    windows = _daily_windows(start_ts, end_ts)
    all_trades: list[dict] = []

    for window_start, window_end in windows:
        window_trades = await _fetch_trades_window(client, wallet, window_start, window_end)
        all_trades.extend(window_trades)

    logger.info(
        "Fetched %d trades for wallet %s (%d windows)",
        len(all_trades), wallet, len(windows),
    )
    return all_trades
