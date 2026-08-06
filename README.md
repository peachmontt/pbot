# Polymarket Trading Bot & Wallet Strategy Analyzer

A Python research project for scanning Polymarket markets, testing automated trading strategies, executing CLOB orders, and analyzing public wallet activity to reverse-engineer trading behavior.

The repository contains two main components:

1. **Trading bot**  scans active Polymarket markets and manages entries, take-profit orders, and stop-loss exits.
2. **Wallet analyzer**  downloads public trade history, reconstructs trading rounds, calculates performance metrics, and classifies wallet strategies.

> [!WARNING]
> This project is experimental software, not financial advice. Live trading can result in a complete loss of funds. Start with paper trading, review the code, and use a dedicated wallet with limited funds.

## Features

* Paper trading enabled by default
* Live order execution through the Polymarket CLOB API
* Active binary-market scanning through the Gamma API
* Automatic position and risk-limit management
* Take-profit and stop-loss handling
* Three pluggable trading strategies
* Optional OpenAI or Anthropic signal research
* Wallet credential and USDC.e balance diagnostics
* Public wallet trade-history analysis
* Round-trip reconstruction and MFE/MAE enrichment
* Wallet performance metrics and strategy classification
* Pytest test suite

## Trading strategies

| Strategy  | Description                                                 | Additional configuration                      |
| --------- | ----------------------------------------------------------- | --------------------------------------------- |
| `model_1` | Symmetric range trading around the current YES price        | Default strategy                              |
| `model_2` | Momentum-following directional entries                      | Requires `FEATURE_MODEL_2=true`               |
| `model_3` | AI-generated signals cached by a background research worker | Requires `AI_ENABLED=true` and an LLM API key |

Strategies are loaded dynamically from the `strategies/` package and must expose a `compute_levels(market)` function.

## Requirements

* Python 3.10 or newer
* Internet access to Polymarket APIs
* A Polygon-compatible wallet for live trading
* USDC.e and the required Polymarket allowances for live trading

## Installation

```bash
git clone <repository-url>
cd pbot-main

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

For the AI strategy, install the SDK for the selected provider:

```bash
pip install openai
# or
pip install anthropic
```

## Configuration

Create a local `.env` file in the repository root:

```dotenv
# Safe default: simulate orders without sending transactions
PAPER_TRADING=true

# Trading strategy: model_1, model_2, or model_3
STRATEGY=model_1

# Main loop and order sizing
SCAN_INTERVAL=5
ORDER_BUDGET_USD=1.0
MAX_OPEN_POSITIONS=3
MAX_POSITION_USD=1000.0
MAX_MARKET_HOURS_TO_EXPIRY=24

# Required only for live trading
PRIVATE_KEY=
POLY_SIGNATURE_TYPE=0
FUNDER_ADDRESS=

# Optional Polymarket Builder credentials
POLY_BUILDER_API_KEY=
POLY_BUILDER_SECRET=
POLY_BUILDER_PASSPHRASE=

# model_2
FEATURE_MODEL_2=false

# model_3
AI_ENABLED=false
AI_PROVIDER=openai
AI_MODEL=gpt-5
AI_SCAN_INTERVAL_SEC=60
AI_SIGNAL_TTL_SEC=90
AI_TOP_K=20
AI_MIN_CONFIDENCE=0.65
AI_MIN_ATTENTION=0.70
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Wallet analyzer
ANALYZER_LOOKBACK_DAYS=30
ANALYZER_DB_PATH=data/analyzer.db
ANALYZER_MAX_CONCURRENT_REQUESTS=5
ANALYZER_REQUEST_DELAY_MS=200
```

### Wallet signature types

`POLY_SIGNATURE_TYPE` controls how orders are signed:

* `0`  EOA wallet
* `1`  Polymarket proxy wallet
* `2`  Gnosis Safe

For proxy or Safe accounts, set `FUNDER_ADDRESS` to the address that holds the trading balance.

## Running the bot

### Paper trading

Paper trading is the default and does not submit real orders:

```bash
python bot.py
```

Keep this enabled while validating strategy behavior:

```dotenv
PAPER_TRADING=true
```

The bot will scan eligible markets, calculate entries, simulate fills, and write trading events to its journal output.

### Live trading

Before enabling live mode:

1. Use a dedicated wallet with limited funds.
2. Confirm the configured signer, funder, and signature type.
3. Confirm the wallet has USDC.e on Polygon.
4. Confirm Polymarket exchange allowances are configured.
5. Start with a very small `ORDER_BUDGET_USD`.

Run the wallet diagnostic first:

```bash
python check_wallet.py
```

Then change:

```dotenv
PAPER_TRADING=false
```

Start the bot:

```bash
python bot.py
```

The application performs a connection and balance check and displays a five-second warning before live trading begins.

## Using the wallet analyzer

The analyzer works with public wallet activity and stores processed data in SQLite. It does not require the wallet's private key.

Run the complete analysis pipeline:

```bash
python -m analyzer.cli analyze 0xYOUR_WALLET_ADDRESS --days 30
```

The pipeline:

1. Fetches public trades and market metadata
2. Reconstructs positions and round trips
3. Downloads price history
4. Calculates MFE and MAE
5. Produces wallet-level metrics
6. Classifies the apparent trading strategy

Individual commands are also available:

```bash
python -m analyzer.cli fetch 0xYOUR_WALLET_ADDRESS --days 30
python -m analyzer.cli build-rounds 0xYOUR_WALLET_ADDRESS
python -m analyzer.cli metrics 0xYOUR_WALLET_ADDRESS
python -m analyzer.cli classify 0xYOUR_WALLET_ADDRESS
```

Use a custom database path when needed:

```bash
python -m analyzer.cli analyze 0xYOUR_WALLET_ADDRESS --db data/custom.db
```

Show all CLI options:

```bash
python -m analyzer.cli --help
```

## Trader screener

`trader_screener.py` downloads recent public trades, calculates approximate trader statistics, and exports CSV files:

```bash
python trader_screener.py
```

Generated files include:

* `polymarket_trades.csv`
* `trader_stats_full.csv`
* `top_profitable_bots.csv`

These files are ignored by Git.

## Tests

Install all dependencies, then run:

```bash
pytest -q
```

Run a specific test file:

```bash
pytest tests/test_positions.py -q
```

## Project structure

```text
.
├── bot.py                 # Main trading loop
├── config.py              # Environment-based bot configuration
├── trader.py              # CLOB client and order execution
├── scanner.py             # Active-market discovery
├── positions.py           # Position lifecycle management
├── price_tracker.py       # Price history and momentum signals
├── journal.py             # Trading event journal
├── check_wallet.py        # Wallet and balance diagnostic
├── trader_screener.py     # Public trader screening utility
├── ai_research.py         # Background LLM research worker
├── signal_store.py        # Cached AI trading signals
├── strategies/            # Pluggable trading strategies
├── analyzer/              # Public wallet analysis CLI and pipeline
├── tests/                 # Automated tests
└── requirements.txt
```

## Security

Never commit any of the following:

* `.env` files
* wallet private keys
* seed phrases
* Builder API credentials
* OpenAI or Anthropic API keys
* logs containing wallet or account information
* exported databases or trading datasets

Before pushing changes, check the staged diff:

```bash
git diff --cached
```

You can also scan the repository history with tools such as Gitleaks or TruffleHog. If a private key has ever been committed, deleting it from the latest commit is not enough: rotate the key and move any remaining funds to a new wallet.

## Known limitations

* Strategies are experimental and do not guarantee profitability.
* Paper fills are simulations and may differ significantly from live execution.
* API availability, liquidity, slippage, fees, and market rules can change.
* The wallet analyzer estimates behavior from public data and may not reconstruct every position perfectly.
* AI-generated signals can be inaccurate, stale, or malformed and should not be trusted without independent validation.

## Contributing

Issues and pull requests are welcome. For strategy changes, include tests covering entry filtering, order levels, risk limits, and edge cases.

## License

No license has been added yet. Until a license is provided, the repository remains under the default copyright restrictions.
