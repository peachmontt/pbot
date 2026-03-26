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

# Polymarket signature type: 0 = EOA, 1 = POLY_PROXY, 2 = POLY_GNOSIS_SAFE
POLY_SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "0"))
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS") or None

# Builder API credentials (from Polymarket Builder Settings page)
POLY_BUILDER_API_KEY = os.getenv("POLY_BUILDER_API_KEY") or None
POLY_BUILDER_SECRET = os.getenv("POLY_BUILDER_SECRET") or None
POLY_BUILDER_PASSPHRASE = os.getenv("POLY_BUILDER_PASSPHRASE") or None


def _normalise_private_key(raw: str | None) -> str | None:
    """Accept hex or base64-encoded private keys, always return hex."""
    if not raw:
        return None
    raw = raw.strip().strip('"').strip("'")
    if raw.startswith("0x") or all(c in "0123456789abcdefABCDEF" for c in raw):
        return raw
    import base64
    try:
        decoded = base64.urlsafe_b64decode(raw + "==")
        if len(decoded) == 32:
            return "0x" + decoded.hex()
    except Exception:
        pass
    try:
        decoded = base64.b64decode(raw + "==")
        if len(decoded) == 32:
            return "0x" + decoded.hex()
    except Exception:
        pass
    return raw


PRIVATE_KEY = _normalise_private_key(os.getenv("PRIVATE_KEY"))

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
