# Cross-venue funding logger settings. Edit on the main PC, push, pull on the 24/7 PC.

# Kraken US perps on Bitnomial: coin -> base_symbol (same list as the scan)
BITNOMIAL_COINS = {
    "BTC": "BTCUC", "ETH": "ETHUI", "SOL": "SOLUS", "XRP": "XRPUH", "DOGE": "DOGUK",
    "ADA": "ADAUK", "AVAX": "AVXUD", "LINK": "LNKUD", "DOT": "DOTUH", "LTC": "LTCUS",
    "BCH": "BCHUS", "XLM": "XLMUK", "HBAR": "HBRUK", "XTZ": "XTZUK", "AAVE": "AVEUS",
    "TRX": "TRXUK", "SHIB": "SHBUK",
}

# Names that differ between venues -> one coin name
ALIASES = {"1000SHIB": "SHIB", "KSHIB": "SHIB", "1000PEPE": "PEPE", "ZCASH": "ZEC"}

# Kalshi: only these asset classes are logged (stocks/commodities skipped).
# Matching is case-insensitive "contains".
KALSHI_CRYPTO_CLASSES = ["crypto", "digital"]

# Alerts (yearly %, as decimals: 0.15 = 15%/yr)
STEADY_GAP = 0.15       # 24h-average gap between two venues
SPIKE_GAP = 1.00        # latest single gap between two venues
RESET_FACTOR = 0.8      # alert again only after the gap drops below 80% of its level
MIN_COVERAGE = 0.6      # a venue counts in the 24h average only with 60% of the day logged
                        # (Coinbase hourly: 15 rows; Kraken/Kalshi 8h: 2 rows)
STALE_HOURS = 48        # a venue whose newest row is older than this is left out of gaps

CHECK_MINUTES = 60      # Coinbase funding changes hourly
SUMMARY_HOUR = 9        # daily Telegram summary (PC clock)
SUMMARY_TOP = 5         # how many gaps in the summary
ERROR_ALERT_AFTER = 4   # Telegram alert after this many failed checks in a row, per venue

STATE_FILE = "cross_state.json"
LOG_FILE = "cross_funding.csv"
ERRORS_FILE = "cross_errors.txt"
REQUEST_TIMEOUT = 30
