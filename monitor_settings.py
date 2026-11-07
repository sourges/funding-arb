# ETH funding monitor settings. Edit on the main PC, push, pull on the 24/7 PC.

BASE_SYMBOL = "ETHUI"        # Bitnomial ETH perp (Kraken US "ETH Perp")
KRAKEN_PAIR = "ETHUSD"       # Kraken spot ticker, used for the live cushion check

# The pretend position (same as Backtest 2)
NOTIONAL = 1000.0            # $ of ETH on spot, same qty short on the perp
MARGIN = 740.0               # USD margin on the short
MAINT_RATE = 0.157           # ETH maintenance margin (Kraken spec, Nov 6 2026)

# Alerts
BASELINE_RATE = 0.0001       # alert when a funding interval is NOT this (0.01%)
CUSHION_ALERT = 150.0        # alert when cushion (equity - maintenance) drops below $150
CUSHION_RESET = 200.0        # "cushion OK again" only once it's back above $200
ERROR_ALERT_AFTER = 4        # Telegram alert after this many failed checks in a row

CHECK_MINUTES = 15           # how often to check
SUMMARY_HOUR = 9             # daily Telegram summary at this hour (the PC's clock)

STATE_FILE = "monitor_state.json"
LOG_FILE = "monitor_funding.csv"
ERRORS_FILE = "monitor_errors.txt"
REQUEST_TIMEOUT = 30         # seconds
