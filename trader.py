"""
Polymarket CLOB trader: buy_yes, sell_yes з orderbook check і paper trading.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import Trade

from dotenv import load_dotenv

load_dotenv()

from config import (
    POLYMARKET_CLOB_HOST,
    CHAIN_ID,
    PRIVATE_KEY,
    PAPER_TRADING,
    MIN_ORDER_USD,
    MIN_ORDERBOOK_LIQUIDITY_USD,
)

_client: Any = None


def _ensure_client():
    global _client
    if _client is not None:
        return _client
    key = PRIVATE_KEY or os.getenv("PRIVATE_KEY")
    if not key:
        raise RuntimeError(
            "PRIVATE_KEY не знайдено. Додай PRIVATE_KEY у .env"
        )
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType

    client = ClobClient(POLYMARKET_CLOB_HOST, key=key, chain_id=CHAIN_ID)
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    _client = client
    return client


def _fetch_orderbook_public(token_id: str):
    """Публічний orderbook без auth (для paper mode)."""
    import requests
    url = f"{POLYMARKET_CLOB_HOST.rstrip('/')}/book"
    r = requests.get(url, params={"token_id": token_id}, timeout=10)
    r.raise_for_status()
    return r.json()


def _check_orderbook(token_id: str, side: str, price: float, size: float):
    """
    Перевіряє чи достатньо ліквідності. Повертає (ok, message).
    У paper mode використовує публічний API без ключа.
    """
    notional = price * size
    if notional < MIN_ORDER_USD:
        return False, f"ордер < ${MIN_ORDER_USD}"
    try:
        if PAPER_TRADING:
            data = _fetch_orderbook_public(token_id)
            asks = data.get("asks") or []
            bids = data.get("bids") or []
            levels = asks if side.upper() == "BUY" else bids
        else:
            client = _ensure_client()
            book = client.get_order_book(token_id)
            asks = book.asks or []
            bids = book.bids or []
            levels = asks if side.upper() == "BUY" else bids
            try:
                min_size = float(book.min_order_size or 0)
            except (TypeError, ValueError):
                min_size = 0
            if min_size > 0 and size < min_size:
                return False, f"size {size} < min_order_size {min_size}"
    except Exception as e:
        return False, f"orderbook error: {e}"
    if not levels:
        return False, f"немає {side} ліквідності"
    total_avail = 0.0
    for o in levels:
        try:
            if isinstance(o, (list, tuple)) and len(o) >= 2:
                p, s = float(o[0]), float(o[1])
            elif isinstance(o, dict):
                p = float(o.get("price", 0) or 0)
                s = float(o.get("size", 0) or 0)
            else:
                p = float(getattr(o, "price", 0) or 0)
                s = float(getattr(o, "size", 0) or 0)
            total_avail += p * s
        except (TypeError, ValueError):
            continue
    if total_avail < MIN_ORDERBOOK_LIQUIDITY_USD:
        return False, f"ліквідність ${total_avail:.2f} < ${MIN_ORDERBOOK_LIQUIDITY_USD}"
    return True, "ok"


def buy_yes(token_id: str, price: float, size: float) -> dict:
    """
    BUY YES outcome. У paper mode лише логує.
    """
    ok, msg = _check_orderbook(token_id, "BUY", price, size)
    if not ok:
        return {"success": False, "reason": msg, "paper": PAPER_TRADING}
    if PAPER_TRADING:
        print(f"[PAPER] BUY YES token={token_id[:16]}... price={price} size={size} notional=${price*size:.2f}")
        return {"success": True, "paper": True}
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        client = _ensure_client()
        order = OrderArgs(token_id=token_id, price=price, size=size, side="BUY")
        signed = client.create_order(order)
        resp = client.post_order(signed, OrderType.GTC)
        return {"success": True, "response": resp, "paper": False}
    except Exception as e:
        return {"success": False, "reason": str(e), "paper": False}


def sell_yes(token_id: str, price: float, size: float) -> dict:
    """
    SELL YES outcome (cashout). У paper mode лише логує.
    """
    ok, msg = _check_orderbook(token_id, "SELL", price, size)
    if not ok:
        return {"success": False, "reason": msg, "paper": PAPER_TRADING}
    if PAPER_TRADING:
        print(f"[PAPER] SELL YES token={token_id[:16]}... price={price} size={size} notional=${price*size:.2f}")
        return {"success": True, "paper": True}
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        client = _ensure_client()
        order = OrderArgs(token_id=token_id, price=price, size=size, side="SELL")
        signed = client.create_order(order)
        resp = client.post_order(signed, OrderType.GTC)
        return {"success": True, "response": resp, "paper": False}
    except Exception as e:
        return {"success": False, "reason": str(e), "paper": False}


def execute_trade(opportunity: "Trade | dict") -> None:
    """
    Викликається з bot.py. opportunity — Trade model або dict з token_id, price, size.
    """
    from models import Trade

    trade = opportunity if isinstance(opportunity, Trade) else Trade.from_dict(opportunity)
    if trade is None:
        print("execute_trade: пропущено — потрібні token_id, price, size")
        return
    token_id, price, size, side = trade.token_id, trade.price, trade.size, trade.side
    if not token_id or price <= 0 or size <= 0:
        print("execute_trade: пропущено — потрібні token_id, price, size")
        return
    if side == "SELL":
        result = sell_yes(token_id, price, size)
    else:
        result = buy_yes(token_id, price, size)
    if result.get("success"):
        mode = "PAPER" if result.get("paper") else "LIVE"
        print(f"[{mode}] {side} OK")
    else:
        print(f"execute_trade failed: {result.get('reason', 'unknown')}")
