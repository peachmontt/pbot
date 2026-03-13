"""
Models for trades and order tracking.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class LegType(str, Enum):
    YES = "YES"
    NO = "NO"


@dataclass
class LimitOrder:
    """
    Tracks a single limit order through its lifecycle.
    Used by the range-trading strategy to manage paired YES/NO orders.
    """

    order_id: str | None
    token_id: str
    side: OrderSide
    leg: LegType
    price: float
    size: float
    condition_id: str
    question: str

    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0

    status: OrderStatus = OrderStatus.PENDING
    fill_price: float | None = None
    created_at: float = field(default_factory=time.time)
    filled_at: float | None = None

    def mark_active(self, order_id: str) -> None:
        self.order_id = order_id
        self.status = OrderStatus.ACTIVE

    def mark_filled(self, fill_price: float | None = None) -> None:
        self.status = OrderStatus.FILLED
        self.fill_price = fill_price or self.price
        self.filled_at = time.time()

    def mark_cancelled(self) -> None:
        self.status = OrderStatus.CANCELLED

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.ACTIVE)

    @property
    def notional_usd(self) -> float:
        return self.price * self.size

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "token_id": self.token_id,
            "side": self.side.value,
            "leg": self.leg.value,
            "price": self.price,
            "size": self.size,
            "condition_id": self.condition_id,
            "question": self.question,
            "take_profit_price": self.take_profit_price,
            "stop_loss_price": self.stop_loss_price,
            "status": self.status.value,
            "fill_price": self.fill_price,
        }


@dataclass
class Trade:
    """
    Model for a single trade order. Required by execute_trade / buy_yes / sell_yes.
    """

    token_id: str
    price: float
    size: float
    side: str = "BUY"
    market1: str | None = None
    market2: str | None = None
    edge: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.side, str):
            self.side = self.side.upper()

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "market1": self.market1,
            "market2": self.market2,
            "edge": self.edge,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trade | None:
        token_id = d.get("token_id")
        price = d.get("price")
        size = d.get("size")
        if not token_id or price is None or size is None:
            return None
        try:
            return cls(
                token_id=str(token_id),
                price=float(price),
                size=float(size),
                side=str(d.get("side", "BUY")),
                market1=d.get("market1"),
                market2=d.get("market2"),
                edge=float(d["edge"]) if d.get("edge") is not None else None,
            )
        except (TypeError, ValueError):
            return None
