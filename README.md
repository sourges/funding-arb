# funding-arb

Research for a funding-rate arbitrage strategy: hold a coin on spot, short the same
amount on the perp, collect funding when longs pay shorts.

Venue: Kraken Derivatives US perps (listed on Bitnomial, 8-hour funding at
00:00 / 08:00 / 16:00 UTC, $0.15 per contract per side, USD margin only).

## Step 3: fetch funding history

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python fetch_funding.py --list      # find the base symbols, copy into settings.COINS
python fetch_funding.py             # writes data/funding_<COIN>.csv
python -m unittest discover tests
```

The CSVs in `data/` are committed so the backtest is reproducible.

## ETH funding monitor (paper, 24/7 PC)

Pretend position: $1,000 ETH spot + same qty short on ETH Perp, $740 margin. No orders.
Every 15 min: logs new funding intervals (`monitor_funding.csv`), checks the margin
cushion with Kraken's ETH/USD price, Telegram alerts:
- funding interval not 0.01% (or negative), missing intervals
- cushion below $150 (once; "OK" again above $200)
- 4 failed checks in a row; daily summary at 9 AM

Needs `.env` with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (same as the spread bot).
Run `python main_monitor.py` or `start_monitor.bat`. Settings in `monitor_settings.py`.
Delete `monitor_state.json` to restart the pretend position from the latest interval.

## Cross-venue funding logger (24/7 PC)

Hourly: Kraken US (Bitnomial), Coinbase US perps and Kalshi crypto perps -> one row per
venue / coin / funding time in `cross_funding.csv` (rate, interval, yearly %, price).
Gaps: for a coin on 2+ venues, long the lower rate, short the higher. Telegram:
- steady gap: 24h average >= 15%/yr (once per coin+pair until it drops below 12%)
- spike gap: latest >= 100%/yr (possible quick trade, if fees allow)
- daily summary at 9 AM (top 5 gaps), a venue failing 4 checks in a row
Settings in `cross_settings.py`. Run `python main_cross.py` or `start_cross.bat`.
No orders, no keys. Same `.env` (Telegram) as the ETH monitor.

## Rule

Backtest rules and pass criteria get written down and pushed BEFORE the backtest
is run on the data.
