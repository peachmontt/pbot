import json
import logging
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from config import MAX_MARKET_HOURS_TO_EXPIRY, POLYMARKET_API

log = logging.getLogger(__name__)

FETCH_LIMIT = 500
MAX_PAGES_DEFAULT = 3
MAX_PAGES_EXPIRY = 20


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
    Fetch active binary markets from the Gamma API.

    When MAX_MARKET_HOURS_TO_EXPIRY > 0, uses the API's end_date_min/max
    params to request only near-expiry markets, then applies hour-precision
    filtering client-side. Paginates until all matching markets are fetched.

    When MAX_MARKET_HOURS_TO_EXPIRY == 0, fetches up to MAX_PAGES_DEFAULT
    pages without date filtering.
    """
    use_expiry = MAX_MARKET_HOURS_TO_EXPIRY > 0
    max_pages = MAX_PAGES_EXPIRY if use_expiry else MAX_PAGES_DEFAULT

    now = datetime.now(timezone.utc)
    base_params: dict[str, str] = {
        "active": "true",
        "closed": "false",
        "limit": str(FETCH_LIMIT),
    }
    if use_expiry:
        base_params["end_date_min"] = now.strftime("%Y-%m-%d")
        days_ahead = math.ceil(MAX_MARKET_HOURS_TO_EXPIRY / 24) + 1
        base_params["end_date_max"] = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    markets: list[dict] = []
    seen_conditions: set[str] = set()
    skipped_data = 0
    skipped_expiry = 0
    total_fetched = 0

    for page in range(max_pages):
        try:
            params = {**base_params, "offset": str(page * FETCH_LIMIT)}
            r = requests.get(POLYMARKET_API, params=params, timeout=30)
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

            if use_expiry:
                end_date_str = m.get("endDate") or m.get("end_date_iso")
                if not end_date_str:
                    skipped_expiry += 1
                    continue
                try:
                    end_dt = datetime.fromisoformat(
                        end_date_str.replace("Z", "+00:00"),
                    )
                    hours_left = (end_dt - now).total_seconds() / 3600
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
