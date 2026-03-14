from __future__ import annotations

import logging

from analyzer.api.client import PolymarketClient

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 500
_MAX_OFFSET = 10_000
_WEEK_SECONDS = 7 * 24 * 60 * 60
_ACTIVITY_TYPES = "TRADE,SPLIT,MERGE,REDEEM"


def _weekly_windows(start_ts: int, end_ts: int) -> list[tuple[int, int]]:
    """Split a timestamp range into non-overlapping weekly windows."""
    windows: list[tuple[int, int]] = []
    current = start_ts
    while current < end_ts:
        window_end = min(current + _WEEK_SECONDS, end_ts)
        windows.append((current, window_end))
        current = window_end
    return windows


async def _fetch_activity_window(
    client: PolymarketClient,
    wallet: str,
    start_ts: int,
    end_ts: int,
) -> list[dict]:
    """Fetch all activity pages within a single time window."""
    results: list[dict] = []
    offset = 0

    while offset <= _MAX_OFFSET:
        data, error = await client.get(
            "/activity",
            params={
                "user": wallet,
                "type": _ACTIVITY_TYPES,
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
                "Failed to fetch activity for %s (offset=%d, window=%d-%d): %s",
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


async def fetch_activity(
    client: PolymarketClient,
    wallet: str,
    start_ts: int,
    end_ts: int,
) -> list[dict]:
    """Fetch all activity for a wallet in a date range, splitting into weekly windows to stay within offset limits."""
    windows = _weekly_windows(start_ts, end_ts)
    all_activity: list[dict] = []

    for window_start, window_end in windows:
        window_results = await _fetch_activity_window(client, wallet, window_start, window_end)
        all_activity.extend(window_results)

    logger.info(
        "Fetched %d activity records for wallet %s (%d windows)",
        len(all_activity), wallet, len(windows),
    )
    return all_activity
