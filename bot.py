import logging
import time

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
from scanner import get_markets
from utils import detect_probability_issues
from trader import execute_trade
from config import SCAN_INTERVAL, PAPER_TRADING


def run_bot():
    mode = "PAPER" if PAPER_TRADING else "LIVE"
    print(f"Bot started ({mode} mode). Press Ctrl+C to stop.")
    log = logging.getLogger(__name__)
    while True:
        print("Scanning markets...")
        markets = get_markets()
        opportunities = detect_probability_issues(markets)

        if opportunities:
            log.info("Found %d opportunity/ies, placing order(s)...", len(opportunities))
            for op in opportunities:
                execute_trade(op)
        else:
            n = len(markets) if hasattr(markets, "__len__") else 0
            if n < 2:
                log.info("No edge: need 2+ markets to compare. Have %d.", n)
            else:
                log.info("No edge found: checked %d markets, no pair met MIN_ARBITRAGE. Will retry.", n)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run_bot()
