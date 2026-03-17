"""
AI research worker — enriches markets, prefilters, and queries LLM for signals.

Runs as a background daemon thread on its own cadence (default 60 s).
Writes to signal_store; the main bot loop never calls the LLM directly.

Architecture:
  scanner → enrich → prefilter (top-K) → LLM → signal_store
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from config import (
    AI_MODEL,
    AI_PROVIDER,
    AI_SCAN_INTERVAL_SEC,
    AI_SIGNAL_TTL_SEC,
    AI_TOP_K,
)
from scanner import get_markets
from signal_store import AISignal, SignalStore
from trader import get_best_ask, get_best_bid, get_mid_price

log = logging.getLogger(__name__)

_store: SignalStore | None = None
_worker_thread: threading.Thread | None = None


def get_store() -> SignalStore:
    """Get or create the global SignalStore singleton."""
    global _store
    if _store is None:
        _store = SignalStore()
    return _store


# ---------------------------------------------------------------------------
# Layer 1: Feature enrichment
# ---------------------------------------------------------------------------

def enrich_market(market: dict[str, Any]) -> dict[str, Any]:
    """Add orderbook micro-structure and timing features to a raw market."""
    enriched = dict(market)

    token_id = market["yes_token_id"]
    bid = get_best_bid(token_id)
    ask = get_best_ask(token_id)
    mid = get_mid_price(token_id)

    enriched["bid"] = bid
    enriched["ask"] = ask
    enriched["mid"] = mid
    enriched["spread"] = round(ask - bid, 4) if bid and ask else None

    end_str = market.get("end_date_iso")
    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            enriched["hours_to_expiry"] = round(hours_left, 2)
        except (ValueError, TypeError):
            enriched["hours_to_expiry"] = None
    else:
        enriched["hours_to_expiry"] = None

    return enriched


# ---------------------------------------------------------------------------
# Layer 2: Quant prefilter
# ---------------------------------------------------------------------------

def prefilter(
    markets: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """
    Narrow the universe to top-K candidates worth sending to the LLM.

    Gates: contested price zone, measurable spread, positive liquidity.
    Rank: tightest spread first (most liquid).
    """
    candidates: list[dict[str, Any]] = []

    for m in markets:
        yes_price = float(m.get("yes_price", 0))
        if not (0.20 <= yes_price <= 0.80):
            continue

        spread = m.get("spread")
        if spread is None or spread <= 0:
            continue

        candidates.append(m)

    candidates.sort(key=lambda x: x.get("spread", 999))
    return candidates[:top_k]


# ---------------------------------------------------------------------------
# Layer 3: LLM caller
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a quantitative trading analyst for Polymarket prediction markets.
You receive a batch of markets with enriched data.
Return a JSON object with a single key "signals" containing an array.

For EACH market return EXACTLY this structure:
{
  "condition_id": "<market condition_id>",
  "decision": "BUY_YES" | "BUY_NO" | "WATCH" | "DO_NOT_TRADE",
  "confidence": <0.0-1.0>,
  "attention_score": <0.0-1.0>,
  "entry_min": <float>,
  "entry_max": <float>,
  "take_profit": <float>,
  "stop_loss": <float>,
  "time_horizon_min": <int minutes>,
  "reason_short": "<1 sentence>",
  "tradeable_now": <bool>
}

Rules:
- Only recommend BUY_YES or BUY_NO when confidence >= 0.65 and edge is clear.
- entry_min / entry_max define the acceptable entry zone.
- take_profit and stop_loss must be realistic for the time horizon.
- Return ONLY the JSON object. No markdown, no commentary.\
"""


def _build_user_prompt(markets: list[dict[str, Any]]) -> str:
    lines = ["Analyze these prediction markets and return trading signals:\n"]
    for m in markets:
        lines.append(json.dumps({
            "condition_id": m["condition_id"],
            "question": m["question"],
            "yes_price": m.get("yes_price"),
            "no_price": m.get("no_price"),
            "bid": m.get("bid"),
            "ask": m.get("ask"),
            "spread": m.get("spread"),
            "hours_to_expiry": m.get("hours_to_expiry"),
        }))
    return "\n".join(lines)


def _call_llm(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dispatch to the configured LLM provider and return parsed signals."""
    user_prompt = _build_user_prompt(markets)

    if AI_PROVIDER == "openai":
        return _call_openai(user_prompt)
    if AI_PROVIDER == "anthropic":
        return _call_anthropic(user_prompt)
    raise ValueError(f"Unknown AI_PROVIDER: {AI_PROVIDER}")


def _extract_signals(raw: str) -> list[dict[str, Any]]:
    """Parse LLM text into a list of signal dicts, tolerating minor format quirks."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = json.loads(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "signals" in parsed:
        return parsed["signals"]
    return []


def _call_openai(user_prompt: str) -> list[dict[str, Any]]:
    import os

    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return _extract_signals(resp.choices[0].message.content)


def _call_anthropic(user_prompt: str) -> list[dict[str, Any]]:
    import os

    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=AI_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return _extract_signals(resp.content[0].text)


# ---------------------------------------------------------------------------
# Layer 4: Worker loop
# ---------------------------------------------------------------------------

def _research_cycle(store: SignalStore) -> int:
    """Run one full research cycle. Returns number of signals stored."""
    df = get_markets()
    if df.empty:
        log.info("[AI] No markets to analyze")
        return 0

    raw_markets = df.to_dict("records")

    enriched: list[dict[str, Any]] = []
    for m in raw_markets:
        try:
            enriched.append(enrich_market(m))
        except Exception:
            log.debug("[AI] Failed to enrich %s", m.get("condition_id", "?"))

    shortlist = prefilter(enriched, AI_TOP_K)
    if not shortlist:
        log.info("[AI] No candidates after prefilter (%d enriched)", len(enriched))
        return 0

    log.info(
        "[AI] Analyzing %d candidates (from %d markets)",
        len(shortlist), len(raw_markets),
    )

    try:
        raw_signals = _call_llm(shortlist)
    except Exception:
        log.exception("[AI] LLM call failed")
        return 0

    stored = 0
    for s in raw_signals:
        try:
            signal = AISignal(
                condition_id=s["condition_id"],
                decision=s.get("decision", "WATCH"),
                confidence=float(s.get("confidence", 0)),
                attention_score=float(s.get("attention_score", 0)),
                entry_min=float(s.get("entry_min", 0)),
                entry_max=float(s.get("entry_max", 0)),
                take_profit=float(s.get("take_profit", 0)),
                stop_loss=float(s.get("stop_loss", 0)),
                time_horizon_min=int(s.get("time_horizon_min", 0)),
                reason_short=s.get("reason_short", ""),
                tradeable_now=bool(s.get("tradeable_now", False)),
                ttl_sec=AI_SIGNAL_TTL_SEC,
            )
            store.upsert(signal)
            stored += 1
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("[AI] Skipping malformed signal: %s", exc)

    pruned = store.prune_expired()
    log.info("[AI] Stored %d signals, pruned %d expired", stored, pruned)
    return stored


def _worker_loop(store: SignalStore) -> None:
    """Background loop that runs research cycles on a timer."""
    log.info("[AI] Research worker started (interval=%ds)", AI_SCAN_INTERVAL_SEC)
    while True:
        try:
            _research_cycle(store)
        except Exception:
            log.exception("[AI] Research cycle failed")
        time.sleep(AI_SCAN_INTERVAL_SEC)


def start_worker() -> None:
    """Start the AI research worker as a daemon thread (idempotent)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    store = get_store()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        args=(store,),
        daemon=True,
        name="ai-research",
    )
    _worker_thread.start()
