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

## Rule

Backtest rules and pass criteria get written down and pushed BEFORE the backtest
is run on the data.
