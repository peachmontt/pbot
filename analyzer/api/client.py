from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from types import TracebackType
from typing import TypeVar

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from analyzer.config import settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

GAMMA_API_BASE = "https://gamma-api.polymarket.com"


async def safe(coro: Awaitable[_T]) -> tuple[_T | None, Exception | None]:
    """Central no-throw wrapper — single place that converts exceptions to (None, error) tuples."""
    try:  # noqa: SIM105 — intentional: this is the only try/except in the API layer
        result = await coro
        return result, None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout))


def _log_retry(state: RetryCallState) -> None:
    if state.outcome and state.outcome.failed:
        logger.warning(
            "Retry attempt %d after error: %s",
            state.attempt_number,
            state.outcome.exception(),
        )


class PolymarketClient:
    """Async HTTP client with rate-limiting, exponential-backoff retries, and no-throw error handling."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json"},
        )
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        self._throttle_lock = asyncio.Lock()
        self._delay_s = settings.request_delay_ms / 1000.0
        self._last_request_time: float = 0.0

    @classmethod
    def data_api(cls) -> PolymarketClient:
        return cls(settings.data_api_base)

    @classmethod
    def clob_api(cls) -> PolymarketClient:
        return cls(settings.clob_api_base)

    @classmethod
    def gamma_api(cls) -> PolymarketClient:
        return cls(GAMMA_API_BASE)

    async def __aenter__(self) -> PolymarketClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        """Serialize request starts to enforce minimum delay between requests."""
        async with self._throttle_lock:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_request_time
            if elapsed < self._delay_s:
                await asyncio.sleep(self._delay_s - elapsed)
            self._last_request_time = asyncio.get_running_loop().time()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _do_get(
        self, path: str, params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response

    async def get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
    ) -> tuple[list | dict | None, Exception | None]:
        """Rate-limited GET returning parsed JSON as (data, None) or (None, error)."""
        async with self._semaphore:
            await self._throttle()
            response, error = await safe(self._do_get(path, params))
            if error is not None or response is None:
                logger.error("GET %s%s failed: %s", self._base_url, path, error)
                return None, error
            return response.json(), None
