# Forward test 3 — cross-venue pairs — rules locked BEFORE the data exists (Nov 14, 2026)

Goal: after one falling week (Nov 7–13) showed steady funding gaps, do they still
beat USDC (3.75%/yr) on data that didn't exist when these rules were written,
including an up move? Judged once at the end. No tuning, no re-runs.

## Data
- `cross_funding.csv` from the cross-venue logger on the 24/7 PC, unchanged
- Only rows with funding_time >= 2026-11-15T00:00:00Z count
- `annualized` and `rate` columns as logged (+ = longs pay shorts)

## Test period
- Start: 2026-11-15 00:00 UTC
- BTC reference = Kraken BTC `price` on the first Kraken BTC row at or after the start
- Up move = first Kraken BTC row with price >= 1.10 x reference
- End = 7 days after the up move, or 2026-12-27 00:00 UTC, whichever comes first
- If there was no up move by 2026-12-27: result is INCONCLUSIVE (not pass, not fail),
  the end moves once to 2027-02-07, and the rules stay the same

## Pairs (two groups, judged separately)
- Group A, long Kalshi / short Kraken: AAVE, ADA, BCH, BTC, DOGE, ETH, LINK, LTC, SHIB, SOL, XRP
- Group B, long Coinbase / short Kraken: AAVE, ADA, AVAX, BCH, BTC, DOGE, DOT, ETH, HBAR,
  LINK, LTC, SHIB, SOL, XLM, XRP
- (Kalshi vs Coinbase pairs such as ZEC are not in this test)

## Signal — checked once a day at 00:00 UTC, using only rows before that time
- gap_7d  = short venue's average annualized minus long venue's, over the previous 7 days
- gap_24h = the same over the previous 24 hours
- A venue's average only counts with >= 60% of its rows present (Coinbase 1h, others 8h)
- Enter (pair not held): gap_7d >= 0.10 (10%/yr)
- Exit (pair held): gap_24h < 0
- Only in-period rows are used, so the first check that can enter is 2026-11-22 00:00 UTC
  (the first full 7 days); checks before that do nothing

## Position and P&L (per pair while held)
- $1,000 notional each leg, kept at $1,000 (price drift ignored)
- Every funding row while held, from the entry check to the exit check:
  - short venue row: + rate x 1000 (received when rate > 0)
  - long venue row:  - rate x 1000 (received when rate < 0)
  - Coinbase rows are hourly, Kalshi/Kraken 8-hourly: each row counts once
- Fees on entry and on exit, each leg, % of $1,000:
  Kraken 0.017%, Kalshi 0.05% (maker), Coinbase 0.02%
- A pair still held at the end pays its exit fees

## Capital and pass — per group
- Capital = $1,320 per held pair ($740 short-leg margin + $580 long-leg margin,
  enough to survive a 50% move against either leg)
- Average capital = $1,320 x average number of pairs held per day over the period
- Annualized return = (net P&L / average capital) x (365 / days in period)
- PASS needs ALL of:
  1. The period contains the up move (else INCONCLUSIVE, see above)
  2. Annualized return > 3.75%
  3. Net P&L > 0 from the up move to the end (the rally part alone)
- If a group never holds a pair: FAIL (nothing to earn)

## Reported, not pass/fail
- Pairs entered and exited, days held, net per pair
- Biggest one-day price move against each held leg (liquidation stress)
- Group P&L before vs after the up move

## After the run
- Result written below. Rules above are NOT changed and re-run.
- PASS -> consider a tiny live trial (sized so a liquidation costs tens of dollars)
- FAIL -> funding arb parked; loggers can be stopped

## Result
(empty until the run)
