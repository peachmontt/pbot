import os

from dotenv import load_dotenv

load_dotenv()

# Polymarket APIs
POLYMARKET_API = "https://gamma-api.polymarket.com/markets"
POLYMARKET_CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

# Keys (зміни тільки в .env)
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Paper trading: True = симуляція, False = реальні ордери
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() in ("true", "1", "yes")

# Торгівля
SCAN_INTERVAL = 2
MIN_ARBITRAGE = 0.05
MIN_ORDER_USD = 1.0  # Polymarket ≈ $1 minimum
MIN_ORDERBOOK_LIQUIDITY_USD = 5.0  # перевіряти перед ордером
DEFAULT_ORDER_SIZE = 10.0  # shares за замовчуванням
