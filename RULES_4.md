# Test 4 — idea 1: do big Coinbase–Kalshi gaps last long enough to beat fees?

Idea 1 from the idea agent (research-notes `projects/idea-agent.md`). The idea, its
signal, its "held" test and its pass bar were written and pushed to research-notes on
2026-11-17 (commit ca063dd), before any in-period data existed. This file copies them
and spells out the details below. Judged once at the end. No tuning, no re-runs.

## Data
- `cross_funding.csv` from the cross-venue logger on the 24/7 PC, unchanged
- Venues `coinbase` and `kalshi` only; coins that appear on both
- `annualized` column as logged (+ = longs pay shorts)
- Only rows with funding_time >= 2026-11-18T00:00:00Z count

## Signal — checked once a day at 00:00 UTC
- For each coin, each venue's 24h average = mean `annualized` of its rows with
  funding_time in [check - 24h, check)
- A venue's average counts only with >= 60% of its rows present:
  Coinbase (1h) 15 rows, Kalshi (8h) 2 rows. Otherwise no signal for that coin that day
- gap_24h = higher venue's average minus lower venue's
- Signal: gap_24h >= 0.20 (20%/yr). Long the lower venue, short the higher
- Every coin that meets this on a check day is one signal, also on days in a row
- Checks: 2026-11-19 00:00 UTC (first with a full in-period day) through
  2026-12-14 00:00 UTC (last whose 72h ends by 2026-12-17 00:00 UTC)

## Held
- After the signal, each venue's 72h average = mean `annualized` of its rows with
  funding_time in [check, check + 72h), with >= 60% of rows present:
  Coinbase 44 rows, Kalshi 6 rows
- gap_72h = short venue's 72h average minus long venue's (same direction as the signal,
  so it is negative if the gap flipped)
- Held: gap_72h >= 0.17 (17%/yr)
- 17%/yr = fee break-even over 3 days: entry + exit, both legs =
  2 x (0.05% Kalshi maker + 0.02% Coinbase) = 0.14% of notional; 0.14% x 365 / 3 = 17.0%
- A signal whose 72h coverage fails on either venue is NOT counted (reported separately)

## Pass
- ALIVE: at least 30 counted signals and at least 60% of them held
- DEAD: at least 30 counted signals and under 60% held
- INCONCLUSIVE: under 30 counted signals
- Judged on or after 2026-12-17 00:00 UTC

## Reported, not pass/fail
- Signals per coin and how many distinct coins (signals on days in a row overlap,
  so 30 signals from 3 coins is weaker than 30 from 15)
- Average gap_24h at signal and average gap_72h after
- Signals dropped for coverage

## After the run
- Result written below and in research-notes (idea 1 row). Rules above are NOT changed
  and re-run.
- ALIVE -> next step is a paper run with real fills and both legs' prices, not money
- DEAD -> Coinbase–Kalshi pairs are noise at this size; the idea log says so

## Result
(empty until the run)
