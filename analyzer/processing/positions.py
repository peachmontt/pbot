from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoundTrip:
    wallet: str
    condition_id: str
    outcome: str
    asset: str
    entry_time: int
    exit_time: int | None
    avg_entry_price: float
    avg_exit_price: float | None
    max_size: float
    total_bought: float
    total_sold: float
    num_entries: int
    num_exits: int
    realized_pnl: float
    hold_duration_sec: int | None
    is_closed: bool
    trades: list[dict[str, Any]] = field(default_factory=list)

    mfe: float | None = None
    mae: float | None = None
    edge_captured: float | None = None


_POSITION_CLOSED_THRESHOLD = 0.001


class _GroupState:
    __slots__ = (
        "position", "avg_entry_price", "realized_pnl",
        "max_size", "num_entries", "num_exits",
        "entry_time", "total_bought", "total_sold",
        "total_sell_value", "trades",
    )

    def __init__(self) -> None:
        self.position: float = 0.0
        self.avg_entry_price: float = 0.0
        self.realized_pnl: float = 0.0
        self.max_size: float = 0.0
        self.num_entries: int = 0
        self.num_exits: int = 0
        self.entry_time: int | None = None
        self.total_bought: float = 0.0
        self.total_sold: float = 0.0
        self.total_sell_value: float = 0.0
        self.trades: list[dict[str, Any]] = []

    def apply_buy(self, price: float, size: float, timestamp: int, trade: dict[str, Any]) -> None:
        self.avg_entry_price = (
            (self.avg_entry_price * self.position + price * size)
            / (self.position + size)
        )
        self.position += size
        self.total_bought += size
        self.num_entries += 1
        if self.position > self.max_size:
            self.max_size = self.position
        if self.entry_time is None:
            self.entry_time = timestamp
        self.trades.append(trade)

    def apply_sell(self, price: float, size: float, trade: dict[str, Any]) -> None:
        self.realized_pnl += (price - self.avg_entry_price) * size
        self.position -= size
        self.total_sold += size
        self.total_sell_value += price * size
        self.num_exits += 1
        self.trades.append(trade)

    def to_round(
        self,
        wallet: str,
        condition_id: str,
        outcome: str,
        asset: str,
        exit_time: int | None,
        is_closed: bool,
    ) -> RoundTrip:
        avg_exit = (
            (self.total_sell_value / self.total_sold) if self.total_sold > 0 else None
        )
        hold_duration = (
            (exit_time - self.entry_time) if is_closed and exit_time and self.entry_time else None
        )
        return RoundTrip(
            wallet=wallet,
            condition_id=condition_id,
            outcome=outcome,
            asset=asset,
            entry_time=self.entry_time or 0,
            exit_time=exit_time,
            avg_entry_price=self.avg_entry_price,
            avg_exit_price=avg_exit,
            max_size=self.max_size,
            total_bought=self.total_bought,
            total_sold=self.total_sold,
            num_entries=self.num_entries,
            num_exits=self.num_exits,
            realized_pnl=self.realized_pnl,
            hold_duration_sec=hold_duration,
            is_closed=is_closed,
            trades=list(self.trades),
        )

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


GroupKey = tuple[str, str, str]  # (condition_id, outcome, asset)


class PositionTracker:
    def process_trades(self, trades: list[dict[str, Any]]) -> list[RoundTrip]:
        if not trades:
            return []

        wallet = trades[0]["wallet"]
        groups: dict[GroupKey, list[dict[str, Any]]] = defaultdict(list)

        for trade in trades:
            key: GroupKey = (trade["condition_id"], trade["outcome"], trade["asset"])
            groups[key].append(trade)

        rounds: list[RoundTrip] = []

        for (condition_id, outcome, asset), group_trades in groups.items():
            sorted_trades = sorted(group_trades, key=lambda t: t["timestamp"])
            state = _GroupState()

            for trade in sorted_trades:
                side = trade["side"].upper()
                price = float(trade["price"])
                size = float(trade["size"])
                timestamp = int(trade["timestamp"])

                if side == "BUY":
                    state.apply_buy(price, size, timestamp, trade)
                elif side == "SELL":
                    state.apply_sell(price, size, trade)

                    if state.position < _POSITION_CLOSED_THRESHOLD:
                        rounds.append(
                            state.to_round(wallet, condition_id, outcome, asset, timestamp, True)
                        )
                        state.reset()

            if state.position >= _POSITION_CLOSED_THRESHOLD:
                rounds.append(
                    state.to_round(wallet, condition_id, outcome, asset, None, False)
                )

        rounds.sort(key=lambda r: r.entry_time)
        return rounds
