# Backtest 1 — rules locked BEFORE running (Nov 6, 2026)

Goal: go / no-go. Does holding a funding-rate arb on Kraken US perps (Bitnomial)
beat leaving the same cash in USDC at 3.75%/yr? No tuning in this run.

## Data
- `data/funding_BTC.csv` (BTCUC, 0.01 BTC) and `data/funding_ETH.csv` (ETHUI, 0.5 ETH)
- All rows as fetched: 2026-05-17 -> 2026-11-05, one row per 8-hour interval
- Spot price = `price_index`, perp price = `mark_price` (both in USD)

## Strategy A — always on (the only strategy in this run)
- Entry at the first row: buy coin on spot worth $1,000 at `price_index`,
  short the same coin quantity on the perp at `mark_price`.
  qty = 1000 / first price_index. qty stays fixed for the whole hold.
- Every row: short receives `funding_rate x qty x mark_price`
  (positive rate = longs pay shorts = we earn; negative = we pay).
- Exit at the last row: sell spot at `price_index`, close short at `mark_price`.
- Basis P&L = qty x [(exit_index - entry_index) - (exit_mark - entry_mark)]

## Costs
- Spot: 0.22% of trade value, entry and exit (Kraken maker)
- Perp: 0.017% of trade value, entry and exit (Kraken Est. Fee $0.13 on 0.01 BTC)
- Round trip ~0.474%

## Capital
- $1,500 = $1,000 spot + $500 USD margin for the short
- Net P&L = funding + basis P&L - fees
- Annualized return = (net / 1500) x (365 / days held)

## Pass — per coin, ALL must hold
1. Annualized return on $1,500 > 3.75%
2. Profitable in both halves: split rows in half by count; each half run as its
   own Strategy A trade (own entry and exit fees), and each must have net > 0

## Also reported (information, not pass/fail)
- Average funding per interval and annualized; % of intervals negative;
  % of intervals exactly 0.0001
- Funding split: how much of the net came from funding vs basis vs fees
- Margin stress: largest short-side loss qty x (mark - entry_mark) during the
  hold vs the $500 margin (would it have needed a top-up?)
- BTC 0.01 (BTCUC) vs BTC 0.0001 (BTCUR) on overlapping intervals: how many
  funding rates match exactly
- Same for ETH (ETHUI vs ETHUL)

## After the run
- Result gets written below, pass or fail. Numbers above are NOT changed and re-run.
- Strategy B (switch on/off by trailing funding) only gets its own locked rules
  if A passes.

## Result
(empty until the run)
