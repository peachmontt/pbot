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
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "5"))

# Order sizing: spend this many USD per side (shares = budget / price)
ORDER_BUDGET_USD = float(os.getenv("ORDER_BUDGET_USD", "1.0"))
MIN_ORDER_USD = 0.10
MIN_ORDERBOOK_LIQUIDITY_USD = 5.0
FEE_RATE = 0.02

# Strategy selection: name of a module inside the strategies/ package
# model_1 = symmetric range trading, model_2 = momentum following
STRATEGY = os.getenv("STRATEGY", "model_1")

# Risk limits (0 = unlimited)
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
MAX_POSITION_USD = float(os.getenv("MAX_POSITION_USD", "1000.0"))

# Only trade markets resolving within this window (0 = no filter)
MAX_MARKET_HOURS_TO_EXPIRY = int(os.getenv("MAX_MARKET_HOURS_TO_EXPIRY", "24"))

# AI strategy (model_3)
AI_ENABLED = os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes")
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")       # openai | anthropic
AI_MODEL = os.getenv("AI_MODEL", "gpt-5")
AI_SCAN_INTERVAL_SEC = int(os.getenv("AI_SCAN_INTERVAL_SEC", "60"))
AI_SIGNAL_TTL_SEC = int(os.getenv("AI_SIGNAL_TTL_SEC", "90"))
AI_TOP_K = int(os.getenv("AI_TOP_K", "20"))
AI_MIN_CONFIDENCE = float(os.getenv("AI_MIN_CONFIDENCE", "0.65"))
AI_MIN_ATTENTION = float(os.getenv("AI_MIN_ATTENTION", "0.70"))
