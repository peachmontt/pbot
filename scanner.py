import json
import logging
import re
import requests
from config import POLYMARKET_API

log = logging.getLogger(__name__)


def _parse_array_maybe_json(value):
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except Exception:
            return None
    return None


# Polymarket іноді пише повні назви
SYMBOLS = {
    "BTC": ["BTC", "Bitcoin"],
    "ETH": ["ETH", "Ethereum"],
    "SOL": ["SOL", "Solana"],
}


def detect_asset(question: str):
    for symbol, variants in SYMBOLS.items():
        for v in variants:
            if v.lower() in question.lower():
                return symbol
    return None


def get_markets():

    log.info("Scanning Gamma API for markets...")

    r = requests.get(
        POLYMARKET_API,
        params={"active": "true", "limit": 200},
        timeout=30,
    )

    r.raise_for_status()

    data = r.json()

    raw_count = len(data) if isinstance(data, list) else 0

    log.info("Fetched %d active markets", raw_count)

    markets = []

    for m in data:

        question = m.get("question")

        if not question:
            continue

        asset = detect_asset(question)

        if not asset:
            continue

        outcomes = _parse_array_maybe_json(m.get("outcomes"))
        prices = _parse_array_maybe_json(m.get("outcomePrices"))

        if not outcomes or not prices:
            continue

        try:
            price = float(prices[0])
        except:
            continue

        token_ids = _parse_array_maybe_json(m.get("clobTokenIds"))

        token_id = token_ids[0] if token_ids else None

        markets.append({
            "asset": asset,
            "question": question,
            "price": price,
            "clob_token_id": token_id,
            "condition_id": m.get("conditionId"),
            "slug": m.get("slug"),
        })

        log.debug("Match %s | price %.2f", asset, price)

    log.info("Filtered to %d markets", len(markets))

    try:
        import pandas as pd
        return pd.DataFrame(markets)
    except:
        return markets