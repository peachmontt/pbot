from __future__ import annotations

import polars as pl


def compute_round_metrics(rounds: list[dict]) -> pl.DataFrame:
    """Enrich raw round dicts with derived per-round metrics.

    Expects the output of ``Repository.get_rounds`` (list of row dicts).
    Returns a polars DataFrame containing every original column plus computed
    metrics such as ``pnl_per_dollar``, ``pnl_bps``, ``hold_minutes``, etc.
    """
    if not rounds:
        return pl.DataFrame()

    df = pl.DataFrame(rounds, infer_schema_length=None)

    notional = pl.col("avg_entry_price") * pl.col("total_bought")

    df = df.with_columns(
        pl.when(notional > 0)
        .then(pl.col("realized_pnl") / notional)
        .otherwise(None)
        .alias("pnl_per_dollar"),
        (pl.col("hold_duration_sec") / 60.0).alias("hold_minutes"),
        (pl.col("hold_duration_sec") / 3600.0).alias("hold_hours"),
        (pl.col("realized_pnl") > 0).alias("is_winner"),
        pl.when(pl.col("total_bought") > 0)
        .then(pl.col("total_sold") / pl.col("total_bought"))
        .otherwise(None)
        .alias("size_ratio"),
        (pl.col("num_entries") - 1).alias("adds_count"),
        pl.when(pl.col("is_closed").cast(pl.Boolean))
        .then(pl.col("num_exits") - 1)
        .otherwise(pl.col("num_exits"))
        .alias("partial_exits_count"),
    ).with_columns(
        (pl.col("pnl_per_dollar") * 10_000).alias("pnl_bps"),
    )

    return df
