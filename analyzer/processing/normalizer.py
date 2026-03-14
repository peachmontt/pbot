from __future__ import annotations

import json
import time
from typing import Any


_TRADE_FIELD_MAP: dict[str, str] = {
    "proxyWallet": "proxy_wallet",
    "conditionId": "condition_id",
    "eventSlug": "event_slug",
    "outcomeIndex": "outcome_index",
    "transactionHash": "tx_hash",
}

_TRADE_PASSTHROUGH: list[str] = [
    "side", "asset", "size", "price", "timestamp",
    "title", "slug", "outcome",
]

_ACTIVITY_FIELD_MAP: dict[str, str] = {
    "proxyWallet": "proxy_wallet",
    "conditionId": "condition_id",
    "eventSlug": "event_slug",
    "outcomeIndex": "outcome_index",
    "transactionHash": "tx_hash",
    "usdcSize": "usdc_size",
}

_ACTIVITY_PASSTHROUGH: list[str] = [
    "type", "side", "asset", "size", "price", "timestamp",
    "title", "slug", "outcome",
]


def _remap(
    raw: dict[str, Any],
    field_map: dict[str, str],
    passthrough: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for api_key, db_key in field_map.items():
        if api_key in raw:
            out[db_key] = raw[api_key]
        elif db_key in raw:
            out[db_key] = raw[db_key]
    for key in passthrough:
        if key in raw:
            out[key] = raw[key]
    return out


def normalize_trades(wallet: str, raw_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = int(time.time())
    seen: set[tuple[str, str | None, str | None, str | None, int | None]] = set()
    results: list[dict[str, Any]] = []

    for raw in raw_trades:
        normalized = _remap(raw, _TRADE_FIELD_MAP, _TRADE_PASSTHROUGH)
        normalized["wallet"] = wallet
        normalized["fetched_at"] = now

        dedup_key = (
            wallet,
            normalized.get("tx_hash"),
            normalized.get("asset"),
            normalized.get("side"),
            normalized.get("timestamp"),
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        results.append(normalized)

    return results


def normalize_activity(wallet: str, raw_activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = int(time.time())
    seen: set[tuple[str, str | None, str | None, str | None, int | None]] = set()
    results: list[dict[str, Any]] = []

    for raw in raw_activity:
        normalized = _remap(raw, _ACTIVITY_FIELD_MAP, _ACTIVITY_PASSTHROUGH)
        normalized["wallet"] = wallet
        normalized["fetched_at"] = now

        dedup_key = (
            wallet,
            normalized.get("tx_hash"),
            normalized.get("type"),
            normalized.get("asset"),
            normalized.get("timestamp"),
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        results.append(normalized)

    return results


def normalize_market(raw_market: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())

    condition_id = raw_market.get("conditionId") or raw_market.get("condition_id")

    tags = raw_market.get("tags")
    category = tags[0] if isinstance(tags, list) and tags else None

    end_date = raw_market.get("endDate") or raw_market.get("end_date_iso")

    is_active: bool | int
    if "active" in raw_market:
        is_active = 1 if raw_market["active"] else 0
    elif "closed" in raw_market:
        is_active = 0 if raw_market["closed"] else 1
    else:
        is_active = 1

    outcomes_raw = raw_market.get("outcomes")
    outcomes = json.dumps(outcomes_raw) if outcomes_raw is not None else None

    tokens_raw = raw_market.get("tokens")
    if isinstance(tokens_raw, list):
        tokens_clean = [
            {"token_id": t.get("token_id") or t.get("tokenID"), "outcome": t.get("outcome")}
            for t in tokens_raw
        ]
        tokens = json.dumps(tokens_clean)
    else:
        tokens = None

    return {
        "condition_id": condition_id,
        "title": raw_market.get("title"),
        "slug": raw_market.get("slug"),
        "event_slug": raw_market.get("eventSlug") or raw_market.get("event_slug"),
        "category": category,
        "end_date": end_date,
        "is_active": is_active,
        "outcomes": outcomes,
        "tokens": tokens,
        "fetched_at": now,
    }
