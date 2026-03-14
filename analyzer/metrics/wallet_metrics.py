from __future__ import annotations

import polars as pl


def compute_wallet_metrics(rounds_df: pl.DataFrame, trades: list[dict]) -> dict:
    """Aggregate round-level and trade-level data into wallet-wide statistics.

    ``rounds_df`` must be the output of :func:`compute_round_metrics` (i.e. it
    already contains computed columns like ``hold_minutes``, ``pnl_bps``, etc.).
    ``trades`` is the raw trade list from the database.
    """
    if rounds_df.is_empty():
        return _empty_metrics()

    trades_df = pl.DataFrame(trades) if trades else pl.DataFrame()

    closed_df = rounds_df.filter(pl.col("is_closed").cast(pl.Boolean))
    total_rounds = rounds_df.height
    closed_rounds = closed_df.height
    open_rounds = total_rounds - closed_rounds
    total_trades = trades_df.height if not trades_df.is_empty() else 0
    unique_markets = rounds_df["condition_id"].n_unique()

    perf = _performance_metrics(closed_df)
    timing = _timing_metrics(closed_df)
    activity = _activity_metrics(trades_df, total_trades)
    sizing = _sizing_metrics(rounds_df)
    direction = _directionality_metrics(trades_df, total_trades)
    mfe_mae = _mfe_mae_metrics(rounds_df)

    return {
        "total_rounds": total_rounds,
        "closed_rounds": closed_rounds,
        "open_rounds": open_rounds,
        "total_trades": total_trades,
        "unique_markets": unique_markets,
        **perf,
        **timing,
        **activity,
        **sizing,
        **direction,
        **mfe_mae,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(val: object, default: float = 0.0) -> float:
    """Safely coerce a polars scalar (possibly ``None``) to ``float``."""
    return float(val) if val is not None else default


def _performance_metrics(closed_df: pl.DataFrame) -> dict:
    if closed_df.is_empty():
        return {
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "median_pnl": 0.0,
            "pnl_stddev": 0.0,
            "best_round_pnl": 0.0,
            "worst_round_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_winner": 0.0,
            "avg_loser": 0.0,
            "expectancy": 0.0,
        }

    pnl = closed_df["realized_pnl"]
    winners = closed_df.filter(pl.col("realized_pnl") > 0)
    losers = closed_df.filter(pl.col("realized_pnl") <= 0)

    win_rate = winners.height / closed_df.height
    sum_wins = _f(winners["realized_pnl"].sum()) if winners.height else 0.0
    sum_losses = abs(_f(losers["realized_pnl"].sum())) if losers.height else 0.0

    if sum_losses > 0:
        profit_factor = sum_wins / sum_losses
    elif sum_wins > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    avg_winner = _f(winners["realized_pnl"].mean()) if winners.height else 0.0
    avg_loser = _f(losers["realized_pnl"].mean()) if losers.height else 0.0
    expectancy = win_rate * avg_winner + (1 - win_rate) * avg_loser

    return {
        "win_rate": win_rate,
        "total_pnl": _f(pnl.sum()),
        "avg_pnl": _f(pnl.mean()),
        "median_pnl": _f(pnl.median()),
        "pnl_stddev": _f(pnl.std()),
        "best_round_pnl": _f(pnl.max()),
        "worst_round_pnl": _f(pnl.min()),
        "profit_factor": profit_factor,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "expectancy": expectancy,
    }


def _timing_metrics(closed_df: pl.DataFrame) -> dict:
    if closed_df.is_empty() or "hold_minutes" not in closed_df.columns:
        return {
            "avg_hold_minutes": 0.0,
            "median_hold_minutes": 0.0,
            "min_hold_minutes": 0.0,
            "max_hold_minutes": 0.0,
        }

    hm = closed_df["hold_minutes"]
    return {
        "avg_hold_minutes": _f(hm.mean()),
        "median_hold_minutes": _f(hm.median()),
        "min_hold_minutes": _f(hm.min()),
        "max_hold_minutes": _f(hm.max()),
    }


def _activity_metrics(trades_df: pl.DataFrame, total_trades: int) -> dict:
    defaults = {
        "trades_per_hour": 0.0,
        "active_hours_per_day": 0.0,
        "active_days": 0,
        "busiest_hour_utc": 0,
    }

    if trades_df.is_empty() or "timestamp" not in trades_df.columns:
        return defaults

    tdf = trades_df.with_columns(
        pl.from_epoch(pl.col("timestamp"), time_unit="s").alias("_dt"),
    ).with_columns(
        pl.col("_dt").dt.date().alias("_date"),
        pl.col("_dt").dt.hour().alias("_hour"),
    )

    active_days = tdf["_date"].n_unique()
    active_hour_slots = tdf.unique(subset=["_date", "_hour"]).height

    trades_per_hour = total_trades / active_hour_slots if active_hour_slots > 0 else 0.0
    hours_per_day = active_hour_slots / active_days if active_days > 0 else 0.0

    busiest = (
        tdf.group_by("_hour")
        .agg(pl.len().alias("cnt"))
        .sort("cnt", descending=True)
    )
    busiest_hour = int(busiest[0, "_hour"]) if busiest.height else 0

    return {
        "trades_per_hour": trades_per_hour,
        "active_hours_per_day": hours_per_day,
        "active_days": active_days,
        "busiest_hour_utc": busiest_hour,
    }


def _sizing_metrics(rounds_df: pl.DataFrame) -> dict:
    notional = (
        rounds_df
        .select((pl.col("avg_entry_price") * pl.col("total_bought")).alias("_notional"))
        ["_notional"]
    )

    return {
        "avg_position_size": _f(rounds_df["max_size"].mean()),
        "median_position_size": _f(rounds_df["max_size"].median()),
        "avg_notional": _f(notional.mean()),
    }


def _directionality_metrics(trades_df: pl.DataFrame, total_trades: int) -> dict:
    if trades_df.is_empty() or total_trades == 0:
        return {
            "buy_sell_ratio": 0.5,
            "pct_trades_both_sides": 0.0,
        }

    buys = trades_df.filter(pl.col("side") == "BUY").height if "side" in trades_df.columns else 0
    buy_sell_ratio = buys / total_trades

    pct_both = 0.0
    if "outcome" in trades_df.columns and "condition_id" in trades_df.columns:
        by_market = trades_df.group_by("condition_id").agg(
            pl.col("outcome").n_unique().alias("n_outcomes"),
        )
        if by_market.height > 0:
            both_count = by_market.filter(pl.col("n_outcomes") > 1).height
            pct_both = both_count / by_market.height

    return {
        "buy_sell_ratio": buy_sell_ratio,
        "pct_trades_both_sides": pct_both,
    }


def _mfe_mae_metrics(rounds_df: pl.DataFrame) -> dict:
    result: dict[str, float] = {}
    for col, key in [("mfe", "avg_mfe"), ("mae", "avg_mae"), ("edge_captured", "avg_edge_captured")]:
        if col in rounds_df.columns:
            non_null = rounds_df[col].drop_nulls()
            result[key] = _f(non_null.mean()) if non_null.len() > 0 else 0.0
        else:
            result[key] = 0.0
    return result


def _empty_metrics() -> dict:
    return {
        "total_rounds": 0,
        "closed_rounds": 0,
        "open_rounds": 0,
        "total_trades": 0,
        "unique_markets": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "avg_pnl": 0.0,
        "median_pnl": 0.0,
        "pnl_stddev": 0.0,
        "best_round_pnl": 0.0,
        "worst_round_pnl": 0.0,
        "profit_factor": 0.0,
        "avg_winner": 0.0,
        "avg_loser": 0.0,
        "expectancy": 0.0,
        "avg_hold_minutes": 0.0,
        "median_hold_minutes": 0.0,
        "min_hold_minutes": 0.0,
        "max_hold_minutes": 0.0,
        "trades_per_hour": 0.0,
        "active_hours_per_day": 0.0,
        "active_days": 0,
        "busiest_hour_utc": 0,
        "avg_position_size": 0.0,
        "median_position_size": 0.0,
        "avg_notional": 0.0,
        "buy_sell_ratio": 0.5,
        "pct_trades_both_sides": 0.0,
        "avg_mfe": 0.0,
        "avg_mae": 0.0,
        "avg_edge_captured": 0.0,
    }
