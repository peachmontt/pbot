import json
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from config import MAX_MARKET_HOURS_TO_EXPIRY, POLYMARKET_API

log = logging.getLogger(__name__)

FETCH_LIMIT = 500
MAX_PAGES = 3


def _parse_array_maybe_json(value):
    """Parse a value that might be a JSON-encoded list or already a list."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def get_markets() -> pd.DataFrame:
    """
    Fetch all active binary markets from the Gamma API.

    Paginates through up to MAX_PAGES * FETCH_LIMIT markets.
    Only filters for valid data (binary outcomes with parseable prices
    and token IDs).
    """
    markets: list[dict] = []
    seen_conditions: set[str] = set()
    skipped_data = 0
    skipped_expiry = 0
    total_fetched = 0

    for page in range(MAX_PAGES):
        try:
            r = requests.get(
                POLYMARKET_API,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": FETCH_LIMIT,
                    "offset": page * FETCH_LIMIT,
                },
                timeout=30,
            )
            r.raise_for_status()
            batch = r.json()
        except requests.RequestException as e:
            log.warning("Failed to fetch markets (page %d): %s", page, e)
            break

        if not isinstance(batch, list) or not batch:
            break

        total_fetched += len(batch)

        for m in batch:
            question = m.get("question")
            if not question:
                continue

            cond_id = m.get("conditionId")
            if cond_id in seen_conditions:
                continue
            seen_conditions.add(cond_id)

            if MAX_MARKET_HOURS_TO_EXPIRY > 0:
                end_date_str = m.get("endDate") or m.get("end_date_iso")
                if not end_date_str:
                    skipped_expiry += 1
                    continue
                try:
                    end_dt = datetime.fromisoformat(
                        end_date_str.replace("Z", "+00:00"),
                    )
                    hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                except (ValueError, TypeError):
                    skipped_expiry += 1
                    continue
                if hours_left <= 0 or hours_left > MAX_MARKET_HOURS_TO_EXPIRY:
                    skipped_expiry += 1
                    continue

            outcomes = _parse_array_maybe_json(m.get("outcomes"))
            prices = _parse_array_maybe_json(m.get("outcomePrices"))
            token_ids = _parse_array_maybe_json(m.get("clobTokenIds"))

            if not outcomes or not prices or len(outcomes) < 2 or len(prices) < 2:
                skipped_data += 1
                continue
            if not token_ids or len(token_ids) < 2:
                skipped_data += 1
                continue

            try:
                yes_price = float(prices[0])
                no_price = float(prices[1])
            except (ValueError, TypeError, IndexError):
                skipped_data += 1
                continue

            yes_token_id = token_ids[0]
            no_token_id = token_ids[1]
            if not yes_token_id or not no_token_id:
                skipped_data += 1
                continue

            markets.append({
                "question": question,
                "condition_id": cond_id,
                "slug": m.get("slug"),
                "end_date_iso": m.get("endDate") or m.get("end_date_iso"),
                "yes_price": yes_price,
                "no_price": no_price,
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
            })

        if len(batch) < FETCH_LIMIT:
            break

    log.info(
        "Fetched %d markets → %d eligible (skipped: %d bad-data, %d expiry-filter)",
        total_fetched, len(markets), skipped_data, skipped_expiry,
    )
    return pd.DataFrame(markets)
