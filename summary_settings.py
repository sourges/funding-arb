# Daily summary for the idea agent. Edit on the main PC, push, pull on the 24/7 PC.
# The summary only READS cross_funding.csv. It never changes it, and it never
# works out how the RULES_3 forward-test pairs are doing.

SUMMARY_FILE = "agent_summary.txt"   # written next to cross_funding.csv (gitignored)

TOP = 10                 # how many lines per section
PERSIST_GAP = 0.10       # a "streak" day needs a gap of at least 10%/yr (0.10)
LOOKBACK_DAYS = 7        # flips, venue habits and the long average use this many days
MIN_COVERAGE = 0.6       # a venue's day counts only with 60% of its rows logged
STALE_HOURS = 48         # same meaning as in cross_settings
PRICE_VENUES = ["kraken", "coinbase", "kalshi"]   # first venue that has the coin gives its price

# Not crypto: left out of the whole summary (the log still keeps them).
# Coinbase lists stock-index and gold perps next to its crypto ones; add new ones here.
EXCLUDE_COINS = ["CHINA", "TECH", "US 500", "DFNSE", "PAXG", "AI"]
