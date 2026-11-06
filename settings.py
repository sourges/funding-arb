# Settings for the funding-rate fetcher. Edit here, push, pull on the other PC.

# Bitnomial public REST API (no key needed). Kraken US perps are listed on Bitnomial.
# If requests fail with 404, try "https://bitnomial.com/exchange/api/v1/prod".
BASE_URL = "https://bitnomial.com/exchange/api/v1"

# coin name (used for the CSV filename) -> Bitnomial base_symbol.
# Fill in the base symbols after running:  python fetch_funding.py --list
COINS = {
    "BTC": "",
    "ETH": "",
    "DOGE": "",
}

# Fetch history from this time (UTC, ISO 8601). Kraken US perps launched ~June 2026,
# so anything earlier just returns from the first funding interval.
BEGIN_TIME = "2026-01-01T00:00:00Z"

PAGE_LIMIT = 100          # rows per request
DATA_DIR = "data"         # CSVs land here: data/funding_<COIN>.csv
REQUEST_TIMEOUT = 30      # seconds
