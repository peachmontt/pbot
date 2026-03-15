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

# Order sizing: spend this many USD per side (shares = budget / price)
ORDER_BUDGET_USD = 1.0
MIN_ORDER_USD = 0.10
MIN_ORDERBOOK_LIQUIDITY_USD = 5.0
FEE_RATE = 0.02

# Strategy selection: name of a module inside the strategies/ package
# model_1 = symmetric range trading, model_2 = momentum following
STRATEGY = os.getenv("STRATEGY", "model_2")

# Risk limits (0 = unlimited)
MAX_OPEN_POSITIONS = 0
MAX_POSITION_USD = 1000.0
