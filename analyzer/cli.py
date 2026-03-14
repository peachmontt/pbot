from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from analyzer.api.client import PolymarketClient
from analyzer.api.activity import fetch_activity
from analyzer.api.markets import fetch_markets_batch
from analyzer.api.prices import fetch_prices_batch
from analyzer.api.trades import fetch_all_trades
from analyzer.config import settings
from analyzer.db import Repository, init_db
from analyzer.metrics.classification import StrategyProfile, classify_strategy
from analyzer.metrics.round_metrics import compute_round_metrics
from analyzer.metrics.wallet_metrics import compute_wallet_metrics
from analyzer.processing.enrichment import enrich_trades_with_market_data
from analyzer.processing.normalizer import normalize_market, normalize_trades
from analyzer.processing.positions import PositionTracker
from analyzer.processing.rounds import enrich_rounds_with_mfe_mae, rounds_to_db_dicts

app = typer.Typer(
    name="analyzer",
    help="Reverse-engineer Polymarket bot trading strategies from public trade data.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger("analyzer")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _resolve_db_path(db: str | None) -> Path:
    return Path(db) if db else settings.db_path


# ── fetch command ──────────────────────────────────────────────────────────


async def _fetch(wallet: str, days: int, db_path: Path) -> None:
    await init_db(db_path)

    end_ts = int(time.time())
    start_ts = end_ts - days * 86400

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        # 1. Fetch trades
        task = progress.add_task("Fetching trades...", total=None)
        async with PolymarketClient.data_api() as data_client:
            raw_trades = await fetch_all_trades(data_client, wallet, start_ts, end_ts)
        progress.update(task, description=f"Fetched {len(raw_trades)} trades")
        progress.stop_task(task)

        # 2. Normalize and store
        task2 = progress.add_task("Storing trades...", total=None)
        normalized = normalize_trades(wallet, raw_trades)
        with Repository(db_path) as repo:
            inserted = repo.insert_trades(normalized)
        progress.update(task2, description=f"Stored {inserted} new trades ({len(normalized)} total)")
        progress.stop_task(task2)

        # 3. Fetch market metadata for all unique condition_ids
        task3 = progress.add_task("Fetching market metadata...", total=None)
        with Repository(db_path) as repo:
            condition_ids = repo.get_unique_condition_ids(wallet)

        async with PolymarketClient.gamma_api() as gamma_client:
            raw_markets = await fetch_markets_batch(gamma_client, condition_ids)

        with Repository(db_path) as repo:
            for raw_mkt in raw_markets:
                normalized_mkt = normalize_market(raw_mkt)
                repo.insert_market(normalized_mkt)
        progress.update(
            task3,
            description=f"Stored metadata for {len(raw_markets)} markets",
        )
        progress.stop_task(task3)

        # 4. Fetch price history for assets not yet cached
        task4 = progress.add_task("Fetching price history...", total=None)
        with Repository(db_path) as repo:
            all_assets = repo.get_unique_assets(wallet)
            assets_to_fetch = repo.get_assets_missing_prices(wallet)

        cached = len(all_assets) - len(assets_to_fetch)
        if cached:
            progress.update(task4, description=f"Fetching price history ({cached} cached, {len(assets_to_fetch)} remaining)...")

        def _on_price_progress(done: int, total: int) -> None:
            progress.update(task4, description=f"Fetching price history... {done + cached}/{len(all_assets)} assets")

        async with PolymarketClient.clob_api() as clob_client:
            results = await fetch_prices_batch(
                clob_client, assets_to_fetch, start_ts, end_ts,
                on_progress=_on_price_progress,
            )

        with Repository(db_path) as repo:
            for asset_id, points in results.items():
                price_dicts = [{"timestamp": p["t"], "price": p["p"]} for p in points]
                repo.insert_price_history(asset_id, price_dicts)

        progress.update(task4, description=f"Fetched price history for {len(results) + cached}/{len(all_assets)} assets")
        progress.stop_task(task4)

    console.print(
        Panel(
            f"[green]Fetch complete for {wallet}[/]\n"
            f"Trades: {len(raw_trades)} | Markets: {len(raw_markets)} | Price series: {count}",
            title="Done",
        )
    )


@app.command()
def fetch(
    wallet: str = typer.Argument(..., help="Wallet address (0x-prefixed)"),
    days: int = typer.Option(30, "--days", "-d", help="Lookback period in days"),
    db: str | None = typer.Option(None, "--db", help="Custom database path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fetch all trades, market metadata, and price history for a wallet."""
    _setup_logging(verbose)
    asyncio.run(_fetch(wallet, days, _resolve_db_path(db)))


# ── build-rounds command ───────────────────────────────────────────────────


@app.command("build-rounds")
def build_rounds(
    wallet: str = typer.Argument(..., help="Wallet address"),
    db: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Reconstruct positions and detect round-trips from stored trades."""
    _setup_logging(verbose)
    db_path = _resolve_db_path(db)

    with Repository(db_path) as repo:
        trades = repo.get_trades(wallet)
        if not trades:
            console.print(f"[yellow]No trades found for {wallet}. Run 'fetch' first.[/]")
            raise typer.Exit(1)

        console.print(f"Processing {len(trades)} trades...")

        markets_raw = repo.get_all_markets()
        market_lookup = {m["condition_id"]: m for m in markets_raw}
        enriched = enrich_trades_with_market_data(trades, market_lookup)

        tracker = PositionTracker()
        round_trips = tracker.process_trades(enriched)

        def price_getter(asset: str, start_ts: int, end_ts: int) -> list[dict]:
            return repo.get_price_history(asset, start_ts, end_ts)

        round_trips = enrich_rounds_with_mfe_mae(round_trips, price_getter)

        repo.clear_rounds(wallet)
        db_dicts = rounds_to_db_dicts(wallet, round_trips)
        inserted = repo.insert_rounds(db_dicts)

    closed = sum(1 for r in round_trips if r.is_closed)
    console.print(
        Panel(
            f"[green]Rounds built for {wallet}[/]\n"
            f"Total: {len(round_trips)} | Closed: {closed} | Open: {len(round_trips) - closed}",
            title="Round-trips",
        )
    )


# ── metrics command ────────────────────────────────────────────────────────


@app.command()
def metrics(
    wallet: str = typer.Argument(..., help="Wallet address"),
    db: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Compute and display metrics for a wallet's trading rounds."""
    _setup_logging(verbose)
    db_path = _resolve_db_path(db)

    with Repository(db_path) as repo:
        rounds = repo.get_rounds(wallet)
        trades = repo.get_trades(wallet)

    if not rounds:
        console.print(f"[yellow]No rounds found for {wallet}. Run 'build-rounds' first.[/]")
        raise typer.Exit(1)

    rounds_df = compute_round_metrics(rounds)
    wallet_m = compute_wallet_metrics(rounds_df, trades)

    _print_metrics_table(wallet, wallet_m)


def _print_metrics_table(wallet: str, m: dict) -> None:
    table = Table(title=f"Wallet Metrics: {wallet[:10]}...{wallet[-6:]}", show_lines=True)
    table.add_column("Category", style="bold cyan", width=20)
    table.add_column("Metric", width=25)
    table.add_column("Value", justify="right", width=18)

    _section = [
        ("General", [
            ("Total rounds", f"{m['total_rounds']}"),
            ("Closed / Open", f"{m['closed_rounds']} / {m['open_rounds']}"),
            ("Total trades", f"{m['total_trades']}"),
            ("Unique markets", f"{m['unique_markets']}"),
        ]),
        ("Performance", [
            ("Win rate", f"{m['win_rate']:.1%}"),
            ("Total PnL", f"${m['total_pnl']:.2f}"),
            ("Avg PnL / round", f"${m['avg_pnl']:.4f}"),
            ("Median PnL / round", f"${m['median_pnl']:.4f}"),
            ("Profit factor", f"{m['profit_factor']:.2f}"),
            ("Expectancy", f"${m['expectancy']:.4f}"),
            ("Best round", f"${m['best_round_pnl']:.2f}"),
            ("Worst round", f"${m['worst_round_pnl']:.2f}"),
        ]),
        ("Timing", [
            ("Avg hold", f"{m['avg_hold_minutes']:.1f} min"),
            ("Median hold", f"{m['median_hold_minutes']:.1f} min"),
            ("Min / Max hold", f"{m['min_hold_minutes']:.1f} / {m['max_hold_minutes']:.1f} min"),
        ]),
        ("Activity", [
            ("Trades/hour", f"{m['trades_per_hour']:.1f}"),
            ("Active hours/day", f"{m['active_hours_per_day']:.1f}"),
            ("Active days", f"{m['active_days']}"),
            ("Busiest hour (UTC)", f"{m['busiest_hour_utc']}:00"),
        ]),
        ("Sizing", [
            ("Avg position size", f"{m['avg_position_size']:.2f}"),
            ("Avg notional", f"${m['avg_notional']:.2f}"),
        ]),
        ("Direction", [
            ("Buy/Sell ratio", f"{m['buy_sell_ratio']:.2f}"),
            ("Both sides %", f"{m['pct_trades_both_sides']:.1%}"),
        ]),
        ("MFE / MAE", [
            ("Avg MFE", f"{m['avg_mfe']:.4f}"),
            ("Avg MAE", f"{m['avg_mae']:.4f}"),
            ("Avg edge captured", f"{m['avg_edge_captured']:.2%}"),
        ]),
    ]

    for category, rows in _section:
        for i, (metric, value) in enumerate(rows):
            table.add_row(category if i == 0 else "", metric, value)

    console.print(table)


# ── classify command ───────────────────────────────────────────────────────


@app.command()
def classify(
    wallet: str = typer.Argument(..., help="Wallet address"),
    db: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Classify the trading strategy for a wallet."""
    _setup_logging(verbose)
    db_path = _resolve_db_path(db)

    with Repository(db_path) as repo:
        rounds = repo.get_rounds(wallet)
        trades = repo.get_trades(wallet)

    if not rounds:
        console.print(f"[yellow]No rounds found for {wallet}. Run 'build-rounds' first.[/]")
        raise typer.Exit(1)

    rounds_df = compute_round_metrics(rounds)
    wallet_m = compute_wallet_metrics(rounds_df, trades)
    profile = classify_strategy(wallet_m, rounds_df, trades)

    _print_classification(wallet, profile)


def _print_classification(wallet: str, p: StrategyProfile) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold]{p.primary_strategy}[/] (confidence: {p.confidence:.0%})",
            title=f"Strategy Classification: {wallet[:10]}...{wallet[-6:]}",
            border_style="green" if p.confidence >= 0.5 else "yellow",
        )
    )

    if p.evidence:
        console.print("\n[bold]Evidence:[/]")
        for ev in p.evidence:
            console.print(f"  - {ev}")

    console.print("\n[bold]All scores:[/]")
    scores_table = Table(show_header=True, header_style="bold")
    scores_table.add_column("Strategy")
    scores_table.add_column("Score", justify="right")
    for name, score in sorted(p.scores.items(), key=lambda kv: kv[1], reverse=True):
        marker = " <--" if name == p.primary_strategy else ""
        scores_table.add_row(name, f"{score:.2f}{marker}")
    console.print(scores_table)

    console.print(f"\n[dim]{p.summary}[/]\n")


# ── analyze (full pipeline) ───────────────────────────────────────────────


@app.command()
def analyze(
    wallet: str = typer.Argument(..., help="Wallet address"),
    days: int = typer.Option(30, "--days", "-d"),
    db: str | None = typer.Option(None, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full pipeline: fetch -> build-rounds -> metrics -> classify."""
    _setup_logging(verbose)
    db_path = _resolve_db_path(db)

    console.print(Panel(f"[bold]Full analysis for {wallet}[/]\nLookback: {days} days", title="Analyze"))

    console.rule("Step 1/4: Fetch data")
    asyncio.run(_fetch(wallet, days, db_path))

    console.rule("Step 2/4: Build rounds")
    build_rounds(wallet, str(db_path), verbose)

    console.rule("Step 3/4: Compute metrics")
    metrics(wallet, str(db_path), verbose)

    console.rule("Step 4/4: Classify strategy")
    classify(wallet, str(db_path), verbose)


if __name__ == "__main__":
    app()
