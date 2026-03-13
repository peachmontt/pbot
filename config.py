import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Polymarket APIs
POLYMARKET_API = "https://gamma-api.polymarket.com/markets"
POLYMARKET_CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

# Binance public API (no auth needed)
BINANCE_API = "https://api.binance.com/api/v3"
BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}

# Keys
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Paper trading: True = simulation, False = real orders
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() in ("true", "1", "yes")

# Scanning
SCAN_INTERVAL = 1

# Order sizing
DEFAULT_ORDER_SIZE = 10.0
MIN_ORDER_USD = 1.0
MIN_ORDERBOOK_LIQUIDITY_USD = 5.0
FEE_RATE = 0.02

# Range trading: spread is the distance from mid-price to each limit order.
# Volatility determines the spread between MIN and MAX.
#   Low vol  → half_spread = 0.06 → buy at $0.44, sell at $0.56 (around $0.50)
#   High vol → half_spread = 0.07 → buy at $0.43, sell at $0.57 (around $0.50)
MIN_HALF_SPREAD = 0.06
MAX_HALF_SPREAD = 0.07

# Stop-loss: close with market order if price moves this far against entry
STOP_LOSS_PCT = 0.20

# Volatility thresholds (stddev of hourly returns over the window)
VOLATILITY_WINDOW_HOURS = 24
VOLATILITY_LOW = 0.005
VOLATILITY_HIGH = 0.025

# Market quality filters
MIN_MARKET_VOLUME_USD = 1000.0
MIN_DAYS_TO_EXPIRY = 30

# Risk limits
MAX_OPEN_POSITIONS = 10
MAX_POSITION_USD = 100.0
