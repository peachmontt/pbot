"""
Polymarket CLOB trader: limit orders, cancellation, market exit, and paper trading.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from config import (
    CHAIN_ID,
    MIN_ORDER_USD,
    MIN_ORDERBOOK_LIQUIDITY_USD,
    PAPER_TRADING,
    POLYMARKET_CLOB_HOST,
    PRIVATE_KEY,
)

log = logging.getLogger(__name__)

_client: Any = None


def _ensure_client():
    global _client
    if _client is not None:
        return _client
    key = PRIVATE_KEY or os.getenv("PRIVATE_KEY")
    if not key:
        raise RuntimeError("PRIVATE_KEY not found. Add PRIVATE_KEY to .env")
    from py_clob_client.client import ClobClient

    client = ClobClient(POLYMARKET_CLOB_HOST, key=key, chain_id=CHAIN_ID)
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    _client = client
    return client


def verify_connection() -> dict[str, Any]:
    """Test CLOB client connectivity at startup. Returns {success, reason?}."""
    try:
        _ensure_client()
        log.info("CLOB client connected successfully")
        return {"success": True}
    except Exception as e:
        return {"success": False, "reason": str(e)}


def _fetch_orderbook_public(token_id: str) -> dict:
    import requests

    url = f"{POLYMARKET_CLOB_HOST.rstrip('/')}/book"
    r = requests.get(url, params={"token_id": token_id}, timeout=10)
    r.raise_for_status()
    return r.json()


def get_best_bid(token_id: str) -> float | None:
    """Get the current best bid price for a token."""
    try:
        data = _fetch_orderbook_public(token_id)
        bids = data.get("bids") or []
        if not bids:
            return None
        best = bids[0]
        if isinstance(best, dict):
            return float(best.get("price", 0))
        if isinstance(best, (list, tuple)) and best:
            return float(best[0])
        return None
    except Exception as e:
        log.warning("Failed to get best bid for %s: %s", token_id[:16], e)
        return None


def get_best_ask(token_id: str) -> float | None:
    """Get the current best ask price for a token."""
    try:
        data = _fetch_orderbook_public(token_id)
        asks = data.get("asks") or []
        if not asks:
            return None
        best = asks[0]
        if isinstance(best, dict):
            return float(best.get("price", 0))
        if isinstance(best, (list, tuple)) and best:
            return float(best[0])
        return None
    except Exception as e:
        log.warning("Failed to get best ask for %s: %s", token_id[:16], e)
        return None


def get_mid_price(token_id: str) -> float | None:
    """Get current mid-price from the orderbook."""
    try:
        data = _fetch_orderbook_public(token_id)
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        if not bids or not asks:
            return None
        best_bid = float(bids[0]["price"]) if isinstance(bids[0], dict) else float(bids[0][0])
        best_ask = float(asks[0]["price"]) if isinstance(asks[0], dict) else float(asks[0][0])
        return (best_bid + best_ask) / 2.0
    except Exception as e:
        log.warning("Failed to get mid price for %s: %s", token_id[:16], e)
        return None


# ---------------------------------------------------------------------------
# Limit orders
# ---------------------------------------------------------------------------

def place_limit_order(
    token_id: str,
    price: float,
    size: float,
    side: str = "BUY",
) -> dict[str, Any]:
    """
    Place a GTC limit order on the CLOB.

    Returns: {success: bool, order_id: str|None, paper: bool, reason: str|None}
    """
    notional = price * size
    if notional < MIN_ORDER_USD:
        return {"success": False, "order_id": None, "paper": PAPER_TRADING,
                "reason": f"notional ${notional:.2f} < ${MIN_ORDER_USD}"}

    if PAPER_TRADING:
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        log.info(
            "[PAPER] LIMIT %s token=%s... price=%.3f size=%.1f id=%s",
            side, token_id[:16], price, size, order_id,
        )
        return {"success": True, "order_id": order_id, "paper": True}

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = _ensure_client()
        order = OrderArgs(token_id=token_id, price=price, size=size, side=side)
        signed = client.create_order(order)
        resp = client.post_order(signed, OrderType.GTC)
        order_id = resp.get("orderID") or resp.get("id")
        log.info(
            "[LIVE] LIMIT %s token=%s... price=%.3f size=%.1f id=%s",
            side, token_id[:16], price, size, order_id,
        )
        return {"success": True, "order_id": order_id, "paper": False}
    except Exception as e:
        log.warning("place_limit_order failed: %s", e)
        return {"success": False, "order_id": None, "paper": False, "reason": str(e)}


def cancel_order(order_id: str) -> dict[str, Any]:
    """
    Cancel an active order by ID.

    Returns: {success: bool, paper: bool, reason: str|None}
    """
    if PAPER_TRADING:
        log.info("[PAPER] CANCEL order=%s", order_id)
        return {"success": True, "paper": True}

    try:
        client = _ensure_client()
        client.cancel(order_id)
        log.info("[LIVE] CANCEL order=%s", order_id)
        return {"success": True, "paper": False}
    except Exception as e:
        log.warning("cancel_order failed for %s: %s", order_id, e)
        return {"success": False, "paper": False, "reason": str(e)}


def get_order_status(order_id: str) -> dict[str, Any]:
    """
    Check the status of an order.

    Returns: {status: str, filled: bool, paper: bool}
    Possible status values: "LIVE", "MATCHED", "CANCELLED", "UNKNOWN"
    """
    if PAPER_TRADING:
        return {"status": "LIVE", "filled": False, "paper": True}

    try:
        client = _ensure_client()
        order = client.get_order(order_id)
        status = getattr(order, "status", "UNKNOWN")
        filled = status == "MATCHED"
        return {"status": status, "filled": filled, "paper": False}
    except Exception as e:
        log.warning("get_order_status failed for %s: %s", order_id, e)
        return {"status": "UNKNOWN", "filled": False, "paper": False}


def market_sell(token_id: str, size: float) -> dict[str, Any]:
    """
    Aggressive sell for stop-loss: sell at the best available bid.

    In paper mode, simulates the fill at the current best bid.
    In live mode, places a sell at $0.01 (minimum) to ensure fill.
    """
    if PAPER_TRADING:
        bid = get_best_bid(token_id)
        fill_price = bid or 0.01
        log.info(
            "[PAPER] MARKET SELL token=%s... size=%.1f fill=%.3f",
            token_id[:16], size, fill_price,
        )
        return {"success": True, "fill_price": fill_price, "paper": True}

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = _ensure_client()
        order = OrderArgs(token_id=token_id, price=0.01, size=size, side="SELL")
        signed = client.create_order(order)
        resp = client.post_order(signed, OrderType.GTC)
        log.info("[LIVE] MARKET SELL token=%s... size=%.1f", token_id[:16], size)
        return {"success": True, "fill_price": 0.01, "response": resp, "paper": False}
    except Exception as e:
        log.warning("market_sell failed: %s", e)
        return {"success": False, "fill_price": None, "paper": False, "reason": str(e)}
