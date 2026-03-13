import json
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

from config import MIN_DAYS_TO_EXPIRY, MIN_MARKET_VOLUME_USD, POLYMARKET_API

log = logging.getLogger(__name__)


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


SYMBOLS = {
    "BTC": ["BTC", "Bitcoin"],
    "ETH": ["ETH", "Ethereum"],
    "SOL": ["SOL", "Solana"],
}


def detect_asset(question: str) -> Optional[str]:
    for symbol, variants in SYMBOLS.items():
        for v in variants:
            if v.lower() in question.lower():
                return symbol
    return None


def _parse_end_date(m: dict) -> Optional[datetime]:
    """Try to extract a timezone-aware end date from Gamma API market data."""
    for field in ("endDate", "endDateIso", "end_date_iso"):
        raw = m.get(field)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            continue
    return None


def _parse_volume(m: dict) -> float:
    """Best-effort extraction of volume in USD, preferring 24h then all-time."""
    for field in ("volume24hr", "volumeNum", "volume"):
        raw = m.get(field)
        if raw is None:
            continue
        try:
            val = float(raw)
            if val > 0:
                return val
        except (ValueError, TypeError):
            continue
    return 0.0


SEARCH_QUERIES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
}

MARKETS_PER_ASSET = 30


def _fetch_markets_for_asset(asset: str, query: str) -> list[dict]:
    """Fetch markets for a single asset using the Gamma API text search."""
    r = requests.get(
        POLYMARKET_API,
        params={"active": "true", "closed": "false", "limit": MARKETS_PER_ASSET, "q": query},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    log.debug("Fetched %d markets for %s (q=%s)", len(data), asset, query)
    return data if isinstance(data, list) else []


def get_markets() -> pd.DataFrame:
    """
    Fetch active BTC/ETH/SOL binary markets from the Gamma API.

    Makes one targeted request per asset (3 total) instead of fetching
    all 200+ markets. Applies quality filters on volume and expiry.
    """
    log.info("Scanning Gamma API for BTC/ETH/SOL markets...")

    now = datetime.now(timezone.utc)
    markets = []
    seen_conditions: set[str] = set()
    skipped_volume = 0
    skipped_expiry = 0
    skipped_data = 0
    total_fetched = 0

    for asset, query in SEARCH_QUERIES.items():
        try:
            raw = _fetch_markets_for_asset(asset, query)
        except requests.RequestException as e:
            log.warning("Failed to fetch %s markets: %s", asset, e)
            continue

        total_fetched += len(raw)

        for m in raw:
            question = m.get("question")
            if not question:
                continue

            detected = detect_asset(question)
            if not detected:
                continue

            cond_id = m.get("conditionId")
            if cond_id in seen_conditions:
                continue
            seen_conditions.add(cond_id)

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

            volume = _parse_volume(m)
            if volume < MIN_MARKET_VOLUME_USD:
                skipped_volume += 1
                continue

            end_date = _parse_end_date(m)
            if end_date is not None:
                days_left = (end_date - now).total_seconds() / 86400
                if days_left < MIN_DAYS_TO_EXPIRY:
                    skipped_expiry += 1
                    continue
            else:
                days_left = None

            markets.append({
                "asset": detected,
                "question": question,
                "condition_id": cond_id,
                "slug": m.get("slug"),
                "yes_price": yes_price,
                "no_price": no_price,
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
                "volume_24h": volume,
                "days_to_expiry": days_left,
            })

    log.info(
        "Fetched %d markets → %d eligible (skipped: %d low-volume, %d near-expiry, %d bad-data)",
        total_fetched, len(markets), skipped_volume, skipped_expiry, skipped_data,
    )
    return pd.DataFrame(markets)
