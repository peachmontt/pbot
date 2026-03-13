"""
Models for trade opportunities.
"""
from dataclasses import dataclass
from typing import Any


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
    def from_dict(cls, d: dict[str, Any]) -> "Trade | None":
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
