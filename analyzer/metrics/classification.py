from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

STRATEGY_MARKET_MAKER = "MARKET_MAKER"
STRATEGY_SCALPER = "SCALPER"
STRATEGY_MOMENTUM = "MOMENTUM"
STRATEGY_MEAN_REVERSION = "MEAN_REVERSION"
STRATEGY_EVENT_DRIVEN = "EVENT_DRIVEN"
STRATEGY_UNKNOWN = "UNKNOWN"

_MIN_CONFIDENCE_THRESHOLD = 0.15


@dataclass
class StrategyProfile:
    primary_strategy: str
    confidence: float
    scores: dict[str, float]
    evidence: list[str] = field(default_factory=list)
    summary: str = ""


def classify_strategy(
    wallet_metrics: dict,
    rounds_df: pl.DataFrame,
    trades: list[dict],
) -> StrategyProfile:
    """Score the wallet against known strategy archetypes and return the best match."""
    if rounds_df.is_empty():
        return StrategyProfile(
            primary_strategy=STRATEGY_UNKNOWN,
            confidence=0.0,
            scores={},
            evidence=["No round data available for classification"],
            summary="Insufficient data to classify trading strategy.",
        )

    scored: dict[str, tuple[float, list[str]]] = {
        STRATEGY_MARKET_MAKER: _score_market_maker(wallet_metrics),
        STRATEGY_SCALPER: _score_scalper(wallet_metrics, rounds_df),
        STRATEGY_MOMENTUM: _score_momentum(wallet_metrics),
        STRATEGY_MEAN_REVERSION: _score_mean_reversion(wallet_metrics, rounds_df),
        STRATEGY_EVENT_DRIVEN: _score_event_driven(wallet_metrics, rounds_df),
    }

    score_values = {name: sv[0] for name, sv in scored.items()}
    evidence_map = {name: sv[1] for name, sv in scored.items()}

    best_name = max(score_values, key=lambda k: score_values[k])
    best_score = score_values[best_name]

    if best_score < _MIN_CONFIDENCE_THRESHOLD:
        return StrategyProfile(
            primary_strategy=STRATEGY_UNKNOWN,
            confidence=0.0,
            scores=score_values,
            evidence=["No strategy pattern scored above the minimum threshold"],
            summary=(
                "The trading pattern does not strongly match any known strategy archetype. "
                "This could indicate a hybrid approach, insufficient data, or a novel strategy."
            ),
        )

    confidence = min(best_score, 1.0)
    evidence = evidence_map[best_name]
    summary = _build_summary(best_name, confidence, score_values, evidence)

    return StrategyProfile(
        primary_strategy=best_name,
        confidence=confidence,
        scores=score_values,
        evidence=evidence,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Per-strategy scoring functions
# ---------------------------------------------------------------------------

def _score_market_maker(m: dict) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []

    bsr = m.get("buy_sell_ratio", 0.5)
    if 0.4 <= bsr <= 0.6:
        score += 0.25
        evidence.append(f"Balanced buy/sell ratio ({bsr:.2f})")

    med_hold = m.get("median_hold_minutes", 0.0)
    if med_hold < 5:
        score += 0.25
        evidence.append(f"Very short hold time (median {med_hold:.1f} min)")

    tph = m.get("trades_per_hour", 0.0)
    if tph > 20:
        score += 0.20
        evidence.append(f"High trading frequency ({tph:.1f} trades/hr)")

    pct_both = m.get("pct_trades_both_sides", 0.0)
    if pct_both > 0.5:
        score += 0.15
        evidence.append(f"Trades both sides in {pct_both:.0%} of markets")

    wr = m.get("win_rate", 0.0)
    avg_pnl_abs = abs(m.get("avg_pnl", 0.0))
    if wr > 0.55 and avg_pnl_abs < 0.5:
        score += 0.15
        evidence.append(f"High win rate ({wr:.0%}) with small avg PnL (${avg_pnl_abs:.2f})")

    return score, evidence


def _score_scalper(m: dict, rounds_df: pl.DataFrame) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []

    med_hold = m.get("median_hold_minutes", 0.0)
    if med_hold < 2:
        score += 0.30
        evidence.append(f"Ultra-short holds (median {med_hold:.1f} min)")

    tph = m.get("trades_per_hour", 0.0)
    if tph > 10:
        score += 0.25
        evidence.append(f"Frequent trading ({tph:.1f} trades/hr)")

    avg_size = m.get("avg_position_size", 0.0)
    med_size = m.get("median_position_size", 0.0)
    if med_size > 0 and avg_size < med_size * 0.5:
        score += 0.20
        evidence.append(f"Small position sizes (avg {avg_size:.2f} vs median {med_size:.2f})")

    if "pnl_bps" in rounds_df.columns:
        closed = rounds_df.filter(pl.col("is_closed").cast(pl.Boolean))
        if closed.height > 0:
            avg_bps = closed["pnl_bps"].mean()
            if avg_bps is not None and 1 <= avg_bps <= 50:
                score += 0.25
                evidence.append(f"Small per-trade edge ({avg_bps:.1f} bps avg)")

    return score, evidence


def _score_momentum(m: dict) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []

    bsr = m.get("buy_sell_ratio", 0.5)
    if bsr > 0.65 or bsr < 0.35:
        direction = "buy-heavy" if bsr > 0.65 else "sell-heavy"
        score += 0.30
        evidence.append(f"Directional bias: {direction} ({bsr:.2f} ratio)")

    med_hold = m.get("median_hold_minutes", 0.0)
    if med_hold > 30:
        score += 0.25
        evidence.append(f"Longer holds suggest trend-following (median {med_hold:.1f} min)")

    avg_mfe = m.get("avg_mfe", 0.0)
    avg_mae = m.get("avg_mae", 0.0)
    if avg_mfe > avg_mae * -1.5:
        score += 0.25
        evidence.append(f"Favorable excursion dominates (MFE {avg_mfe:.4f} vs MAE {avg_mae:.4f})")

    wr = m.get("win_rate", 0.0)
    if 0.35 <= wr <= 0.55:
        score += 0.20
        evidence.append(f"Moderate win rate ({wr:.0%}) typical of momentum")

    return score, evidence


def _score_mean_reversion(m: dict, rounds_df: pl.DataFrame) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []

    if "avg_entry_price" in rounds_df.columns and rounds_df.height > 0:
        extreme_mask = (pl.col("avg_entry_price") < 0.2) | (pl.col("avg_entry_price") > 0.8)
        extreme_frac = rounds_df.filter(extreme_mask).height / rounds_df.height
        if extreme_frac > 0.5:
            score += 0.30
            evidence.append(f"Entries frequently at price extremes ({extreme_frac:.0%} of rounds)")

    edge_cap = m.get("avg_edge_captured", 0.0)
    if edge_cap > 0.5:
        score += 0.25
        evidence.append(f"High edge capture ({edge_cap:.2f})")

    med_hold = m.get("median_hold_minutes", 0.0)
    if 5 <= med_hold <= 120:
        score += 0.25
        evidence.append(f"Medium hold duration (median {med_hold:.1f} min)")

    wr = m.get("win_rate", 0.0)
    if wr > 0.6:
        score += 0.20
        evidence.append(f"High win rate ({wr:.0%})")

    return score, evidence


def _score_event_driven(m: dict, rounds_df: pl.DataFrame) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []

    hours_per_day = m.get("active_hours_per_day", 0.0)
    if hours_per_day < 4:
        score += 0.30
        evidence.append(f"Low daily activity ({hours_per_day:.1f} active hours/day)")

    if "hold_duration_sec" in rounds_df.columns:
        closed = rounds_df.filter(pl.col("is_closed").cast(pl.Boolean))
        if closed.height > 1:
            hd = closed["hold_duration_sec"]
            mean_hd = hd.mean()
            std_hd = hd.std()
            if mean_hd is not None and std_hd is not None and mean_hd > 0:
                cv = std_hd / mean_hd
                if cv > 1.5:
                    score += 0.25
                    evidence.append(f"Highly variable hold times (CV={cv:.2f})")

    avg_size = m.get("avg_position_size", 0.0)
    med_size = m.get("median_position_size", 0.0)
    if med_size > 0 and avg_size > med_size * 1.5:
        score += 0.25
        evidence.append(
            f"Position sizes skewed large (avg {avg_size:.2f} vs median {med_size:.2f})"
        )

    unique_mkts = m.get("unique_markets", 0)
    total_rounds = m.get("total_rounds", 0)
    if unique_mkts < 10 and total_rounds > 20:
        score += 0.20
        evidence.append(f"Concentrated in few markets ({unique_mkts} markets, {total_rounds} rounds)")

    return score, evidence


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

_STRATEGY_LABELS: dict[str, str] = {
    STRATEGY_MARKET_MAKER: "market making",
    STRATEGY_SCALPER: "scalping",
    STRATEGY_MOMENTUM: "momentum/trend-following",
    STRATEGY_MEAN_REVERSION: "mean reversion",
    STRATEGY_EVENT_DRIVEN: "event-driven trading",
}


def _build_summary(
    primary: str,
    confidence: float,
    scores: dict[str, float],
    evidence: list[str],
) -> str:
    label = _STRATEGY_LABELS.get(primary, primary.lower())

    parts: list[str] = [
        f"This wallet's trading behavior is most consistent with a {label} strategy "
        f"(confidence: {confidence:.0%}).",
    ]

    if evidence:
        joined = "; ".join(evidence[:3])
        parts.append(f"Key signals: {joined}.")

    sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(sorted_scores) > 1:
        runner_name, runner_score = sorted_scores[1]
        if runner_score >= _MIN_CONFIDENCE_THRESHOLD:
            runner_label = _STRATEGY_LABELS.get(runner_name, runner_name.lower())
            parts.append(f"Secondary pattern resembles {runner_label} ({runner_score:.0%}).")

    return " ".join(parts)
