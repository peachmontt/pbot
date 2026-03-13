"""
Standalone tool: fetch Polymarket trades, compute per-trader PnL / ROI,
and identify consistently profitable traders (potential bots).
"""
import logging
import time
from typing import Any, Iterable, List

import requests

import pandas as pd

try:
    from tqdm import tqdm  # type: ignore[import-untyped]
except ModuleNotFoundError:
    def tqdm(it: Iterable[Any], desc: str = "") -> Iterable[Any]:  # type: ignore[misc]
        return it

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL = "https://data-api.polymarket.com/trades"
LIMIT = 1000


def fetch_trades(max_pages: int = 100) -> pd.DataFrame:
    all_trades: list[dict[str, Any]] = []
    offset = 0

    for _ in tqdm(range(max_pages), desc="Downloading trades"):
        url = f"{BASE_URL}?limit={LIMIT}&offset={offset}"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException:
            log.warning("Request failed at offset %d, stopping pagination.", offset)
            break

        if not data:
            break

        all_trades.extend(data)
        offset += len(data)
        time.sleep(0.2)

    log.info("Downloaded %d trades across %d pages.", len(all_trades), offset // LIMIT)
    return pd.DataFrame(all_trades)


def _pick_trader_column(df: pd.DataFrame) -> str:
    for c in ("trader", "proxyWallet", "wallet", "user"):
        if c in df.columns:
            return c
    raise SystemExit(
        "Could not find trader identifier column. "
        f"Columns present: {list(df.columns)}"
    )


def _pick_token_columns(df: pd.DataFrame) -> List[str]:
    candidates = [
        ["asset"],
        ["conditionId", "outcomeIndex"],
        ["conditionId", "outcome"],
        ["slug", "outcomeIndex"],
        ["title", "outcome"],
    ]
    for cols in candidates:
        if all(c in df.columns for c in cols):
            return cols
    raise SystemExit(
        "Could not find token identity columns. "
        f"Columns present: {list(df.columns)}"
    )


def calculate_trader_stats(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Preparing data...")

    if "timestamp" in df.columns:
        if pd.api.types.is_numeric_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")

    trader_col = _pick_trader_column(df)
    token_cols = _pick_token_columns(df)

    needed = ["side", "price", "size", trader_col, *token_cols]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {missing}")

    df = df.copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["size"] = pd.to_numeric(df["size"], errors="coerce")
    df = df.dropna(subset=["price", "size", "side", trader_col])

    df["notional_usd"] = df["price"] * df["size"]

    if "timestamp" in df.columns:
        last_prices = (
            df.dropna(subset=["timestamp"])
              .sort_values("timestamp")
              .groupby(token_cols, as_index=False)
              .tail(1)[token_cols + ["price"]]
              .rename(columns={"price": "last_price"})
        )
    else:
        last_prices = (
            df.groupby(token_cols, as_index=False)
              .tail(1)[token_cols + ["price"]]
              .rename(columns={"price": "last_price"})
        )

    buys = df[df["side"] == "BUY"]
    sells = df[df["side"] != "BUY"]

    buy_by = (
        buys.groupby([trader_col] + token_cols, as_index=False)
            .agg(buy_shares=("size", "sum"), buy_usd=("notional_usd", "sum"), buy_trades=("size", "count"))
    )
    sell_by = (
        sells.groupby([trader_col] + token_cols, as_index=False)
             .agg(sell_shares=("size", "sum"), sell_usd=("notional_usd", "sum"), sell_trades=("size", "count"))
    )

    pos = pd.merge(buy_by, sell_by, how="outer", on=[trader_col] + token_cols).fillna(0)
    pos = pd.merge(pos, last_prices, how="left", on=token_cols)
    pos["last_price"] = pos["last_price"].fillna(pos["buy_usd"] / pos["buy_shares"].replace(0, pd.NA))
    pos["last_price"] = pos["last_price"].fillna(0)

    pos["net_cashflow_usd"] = pos["sell_usd"] - pos["buy_usd"]
    pos["net_shares"] = pos["buy_shares"] - pos["sell_shares"]
    pos["m2m_open_usd"] = pos["net_shares"] * pos["last_price"]
    pos["pnl_est_usd"] = pos["net_cashflow_usd"] + pos["m2m_open_usd"]

    stats = (
        pos.groupby(trader_col, as_index=False)
           .agg(
               trades=("buy_trades", "sum"),
               buy_volume=("buy_shares", "sum"),
               sell_volume=("sell_shares", "sum"),
               buy_usd=("buy_usd", "sum"),
               sell_usd=("sell_usd", "sum"),
               net_shares=("net_shares", "sum"),
               net_cashflow_usd=("net_cashflow_usd", "sum"),
               m2m_open_usd=("m2m_open_usd", "sum"),
               pnl_est_usd=("pnl_est_usd", "sum"),
           )
    )

    sell_trades = (
        sell_by.groupby(trader_col, as_index=False)
               .agg(sell_trades=("sell_trades", "sum"))
    )
    stats = pd.merge(stats, sell_trades, how="left", on=trader_col).fillna({"sell_trades": 0})
    stats["trades"] = stats["trades"] + stats["sell_trades"]
    stats = stats.drop(columns=["sell_trades"])

    stats["volume_usd"] = stats["buy_usd"] + stats["sell_usd"]
    stats["roi_est"] = 0.0
    stats.loc[stats["buy_usd"] > 0, "roi_est"] = stats["pnl_est_usd"] / stats["buy_usd"]

    stats = stats.rename(columns={trader_col: "trader"})
    return stats


def detect_profitable_bots(stats: pd.DataFrame) -> pd.DataFrame:
    bots = stats[
        (stats["trades"] > 200) &
        (stats["volume_usd"] > 1000)
    ]
    return bots.sort_values("pnl_est_usd", ascending=False)


def main() -> None:
    log.info("Downloading trades from Polymarket...")

    df = fetch_trades()
    log.info("Trades downloaded: %d", len(df))

    df.to_csv("polymarket_trades.csv", index=False)
    log.info("Saved polymarket_trades.csv")

    stats = calculate_trader_stats(df)
    stats.to_csv("trader_stats_full.csv", index=False)
    log.info("Saved trader_stats_full.csv")

    bots = detect_profitable_bots(stats)
    bots.to_csv("top_profitable_bots.csv", index=False)

    log.info("Top profitable bots:\n%s", bots.head(20).to_string())


if __name__ == "__main__":
    main()
