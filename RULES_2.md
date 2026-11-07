# Backtest 2 — rules locked BEFORE running (Nov 7, 2026)

Goal: does Strategy A still beat USDC at 3.75%/yr once the short has enough
margin to survive a 50% price rise without a top-up?

Everything is the same as Backtest 1 (RULES.md) EXCEPT margin, capital and the
new no-liquidation check.

## Same as Backtest 1
- Data: `data/funding_BTC.csv` (BTCUC), `data/funding_ETH.csv` (ETHUI), all rows
- Strategy A: always on, enter first row, exit last row, qty = 1000 / first price_index, fixed
- Funding, basis P&L and fees calculated exactly as in RULES.md
- Fees: spot 0.22% per side, perp 0.017% per side
- Half split: rows split in half by count, each half its own trade with its own fees

## Changed
- Margin: $740 USD for the short (survives a ~50% rise:
  740 = 1000 x (1.16 x 0.50 + 0.16))
- Capital: $1,740 = $1,000 spot + $740 margin
- Annualized return = (net / 1740) x (365 / days held)

## New check: no liquidation
- Every row: equity = 740 - qty x (mark_price - entry_mark)
- Maintenance = rate x qty x mark_price, rate from Kraken's contract specs
  (Nov 6, 2026 screenshots): BTC 16.1%, ETH 15.7%
- Liquidated if equity < maintenance on any row

## Pass — per coin, ALL must hold
1. Annualized return on $1,740 > 3.75%
2. Profitable in both halves (net > 0 in each)
3. Never liquidated

## Known before running (honesty note)
- From Backtest 1: ETH's biggest rise above entry was ~43.5% and BTC's ~1.8%, so
  check 3 is expected to pass. The 50% level was chosen after seeing that, which
  makes check 3 weak evidence. The real question here is checks 1 and 2.

## After the run
- Result written below, pass or fail. Numbers above are NOT changed and re-run.
- Next idea (separate locked run): keep $500 margin and top up by selling spot
  when the short loss reaches half the margin.

## Result (run Nov 7, 2026)

| | BTC | ETH |
|---|---|---|
| Net (same as Backtest 1) | $35.01 | $51.79 |
| Annualized on $1,740 | 4.26% | 6.30% |
| Half 1 / Half 2 net | $19.81 / $15.41 | $20.10 / $28.09 |
| Smallest margin cushion (equity - maintenance) | $557.56 | $79.42 |
| Liquidated | never | never |
| **Locked verdict** | **PASS** | **PASS** |

### Findings (not part of pass/fail)
- ETH's cushion got down to $79.42 on 2026-09-21 (ETH ~$2,777, +43.5%):
  survived, but close. As noted above, check 3 was expected to pass.
- BTC beats USDC by only ~0.5%/yr (~$9/yr on $1,740). One interval
  (2026-05-28 16:00, 0.424%) paid $3.59 more than a normal 0.01% interval;
  without it BTC would be ~3.82%, barely over the hurdle.
- ETH's edge is larger (~2.5%/yr over USDC) because qty is fixed and funding
  is paid on qty x mark: ETH's price rose ($1,935 -> $2,235) so the position
  grew, while BTC's fell ($85,000 -> ~$76,700) so it shrank. BTC also lost
  $8.35 on basis.
- Both results depend on funding staying at Bitnomial's 0.01% default.
