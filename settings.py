# Settings for the funding-rate fetcher. Edit here, push, pull on the other PC.

# Bitnomial public REST API (no key needed). Kraken US perps are listed on Bitnomial.
# Checked with probe_api.py on Nov 6, 2026:
#   funding rates:  <BASE_URL>/funding-rates/        (no /prod - /prod gives 404)
#   product specs:  <BASE_URL>/prod/product/specs/   (needs /prod)
BASE_URL = "https://bitnomial.com/exchange/api/v1"
FUNDING_PATH = "/funding-rates/"
SPECS_PATH = "/prod/product/specs/"

# coin name (used for the CSV filename) -> Bitnomial base_symbol (from --list).
# Kraken Pro lets you trade BTC in 0.0001 steps and ETH in 0.001 steps, so both sizes
# are fetched to check whether funding is the same. DOGE dropped (thin volume, ~28% margin).
COINS = {
    "BTC": "BTCUC",          # 0.01 BTC
    "BTC_small": "BTCUR",    # 0.0001 BTC - comparison
    "ETH": "ETHUI",          # 0.5 ETH
    "ETH_small": "ETHUL",    # 0.001 ETH - comparison
}

# Fetch history from this time (UTC, ISO 8601). REQUIRED by the API: without it, no rows.
# Perps started trading 2026-05-16, so earlier dates just return from launch.
BEGIN_TIME = "2026-05-01T00:00:00Z"

PAGE_LIMIT = 100          # rows per request
DATA_DIR = "data"         # CSVs land here: data/funding_<COIN>.csv
REQUEST_TIMEOUT = 30      # seconds
