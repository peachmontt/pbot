"""
Price tracker for momentum detection.

Stores rolling price snapshots per token and computes short-term
price changes used by model_2 to detect momentum signals.

Designed to be lightweight — only stores what's needed (15 min of
snapshots at scan-interval resolution).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(slots=True)
class PricePoint:
    timestamp: float
    price: float


_MAX_HISTORY_SECONDS = 20 * 60  # 20 min buffer (>15 min needed)


class PriceTracker:
    """Rolling price history for multiple tokens.

    Call ``update(token_id, price)`` every scan cycle.
    Call ``get_change(token_id, seconds)`` to get the price delta
    over the last N seconds.
    """

    def __init__(self) -> None:
        self._history: dict[str, deque[PricePoint]] = defaultdict(deque)

    def update(self, token_id: str, price: float) -> None:
        now = time.time()
        buf = self._history[token_id]
        buf.append(PricePoint(timestamp=now, price=price))
        cutoff = now - _MAX_HISTORY_SECONDS
        while buf and buf[0].timestamp < cutoff:
            buf.popleft()

    def get_price(self, token_id: str) -> float | None:
        buf = self._history.get(token_id)
        if not buf:
            return None
        return buf[-1].price

    def get_change(self, token_id: str, seconds: int) -> float | None:
        """Price change over the last `seconds`.

        Returns the absolute price difference (current - past).
        If less than `seconds` of history exists, uses the oldest
        available data point so signals can fire immediately.
        Returns None only when fewer than 2 data points exist.
        """
        buf = self._history.get(token_id)
        if not buf or len(buf) < 2:
            return None

        now = buf[-1].timestamp
        target = now - seconds

        past_point = buf[0]
        for point in buf:
            if point.timestamp <= target:
                past_point = point
            else:
                break

        return buf[-1].price - past_point.price

    def get_momentum_signals(self, token_id: str) -> dict[str, float]:
        """Convenience: compute both 5m and 15m changes."""
        change_5m = self.get_change(token_id, 5 * 60)
        change_15m = self.get_change(token_id, 15 * 60)
        return {
            "price_change_5m": change_5m if change_5m is not None else 0.0,
            "price_change_15m": change_15m if change_15m is not None else 0.0,
        }

    def is_warm(self, token_id: str, seconds: int) -> bool:
        """True if token has at least ``seconds`` of collected history."""
        buf = self._history.get(token_id)
        if not buf or len(buf) < 2:
            return False
        return (buf[-1].timestamp - buf[0].timestamp) >= seconds

    def warm_up_summary(self, required_seconds: int = 900) -> tuple[int, int]:
        """Return (warm_count, total_tracked) for the given threshold."""
        total = len(self._history)
        warm = sum(1 for tid in self._history if self.is_warm(tid, required_seconds))
        return warm, total

    @property
    def tracked_count(self) -> int:
        return len(self._history)

    def clear(self) -> None:
        self._history.clear()
