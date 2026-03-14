from __future__ import annotations

import asyncio
import logging

from analyzer.api.client import PolymarketClient

logger = logging.getLogger(__name__)


async def fetch_market(client: PolymarketClient, condition_id: str) -> dict | None:
    """Fetch a single market by condition_id from the Gamma API. Returns None on error or not found."""
    data, error = await client.get("/markets", params={"condition_id": condition_id})
    if error is not None:
        logger.error("Failed to fetch market for condition_id=%s: %s", condition_id, error)
        return None

    if not isinstance(data, list) or len(data) == 0:
        logger.debug("No market found for condition_id=%s", condition_id)
        return None

    return data[0]


async def fetch_event(client: PolymarketClient, event_slug: str) -> dict | None:
    """Fetch event metadata by slug from the Gamma API."""
    data, error = await client.get("/events", params={"slug": event_slug})
    if error is not None:
        logger.error("Failed to fetch event for slug=%s: %s", event_slug, error)
        return None

    if not isinstance(data, list) or len(data) == 0:
        logger.debug("No event found for slug=%s", event_slug)
        return None

    return data[0]


async def fetch_markets_batch(
    client: PolymarketClient,
    condition_ids: list[str],
) -> list[dict]:
    """Fetch markets for multiple condition_ids, deduplicating inputs and filtering failed lookups."""
    unique_ids = list(dict.fromkeys(condition_ids))
    tasks = [fetch_market(client, cid) for cid in unique_ids]
    results = await asyncio.gather(*tasks)

    markets = [m for m in results if m is not None]
    logger.info(
        "Fetched %d/%d markets (from %d unique condition_ids)",
        len(markets), len(unique_ids), len(condition_ids),
    )
    return markets
