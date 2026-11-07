"""Backtest 1 - Strategy A (always on), exactly as locked in RULES.md.

Run:  python backtest.py
Reads data/funding_<COIN>.csv, prints the report per coin.
"""
import csv
from datetime import datetime

# ---- locked in RULES.md (do not tune) ----
NOTIONAL = 1000.0         # $ of coin on spot, same qty shorted on the perp
CAPITAL = 1500.0          # $1,000 spot + $500 margin
SPOT_FEE = 0.0022         # 0.22% per side (Kraken maker)
PERP_FEE = 0.00017        # 0.017% per side (Kraken Est. Fee)
HURDLE = 0.0375           # USDC holding rate, 3.75%/yr
BASELINE_RATE = 0.0001    # the default funding rate seen in the data

COINS = {"BTC": "data/funding_BTC.csv", "ETH": "data/funding_ETH.csv"}
COMPARE = [("BTC", "data/funding_BTC.csv", "data/funding_BTC_small.csv"),
           ("ETH", "data/funding_ETH.csv", "data/funding_ETH_small.csv")]


def _float_or_none(text):
    return None if text == "" else float(text)


def load_rows(filename):
    """Read a funding CSV into dicts with float numbers.

    Bitnomial left price_index blank on 9 rows (Jul 5-6 and Jul 26-27, 2026);
    blanks become None. Strategy A only uses price_index at entry and exit.
    """
    rows = []
    with open(filename, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "interval_start": r["interval_start"],
                "interval_end": r["interval_end"],
                "funding_rate": float(r["funding_rate"]),
                "mark_price": _float_or_none(r["mark_price"]),
                "price_index": _float_or_none(r["price_index"]),
            })
    return rows


def _parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def run_strategy_a(rows, notional=NOTIONAL, capital=CAPITAL,
                   spot_fee=SPOT_FEE, perp_fee=PERP_FEE):
    """Enter at the first row, hold every row, exit at the last row."""
    if not rows:
        raise ValueError("no rows")
    first, last = rows[0], rows[-1]
    entry_index, entry_mark = first["price_index"], first["mark_price"]
    exit_index, exit_mark = last["price_index"], last["mark_price"]
    if None in (entry_index, entry_mark, exit_index, exit_mark):
        raise ValueError(f"missing price at entry {first['interval_start']} "
                         f"or exit {last['interval_start']}")
    if any(r["mark_price"] is None for r in rows):
        raise ValueError("missing mark_price inside the hold (needed for funding)")
    qty = notional / entry_index

    funding = sum(r["funding_rate"] * qty * r["mark_price"] for r in rows)
    basis = qty * ((exit_index - entry_index) - (exit_mark - entry_mark))
    fees = (spot_fee * qty * entry_index + perp_fee * qty * entry_mark
            + spot_fee * qty * exit_index + perp_fee * qty * exit_mark)
    net = funding + basis - fees

    seconds = (_parse_time(last["interval_end"]) - _parse_time(first["interval_start"])).total_seconds()
    days = seconds / 86400
    annualized = (net / capital) * (365 / days)

    # never below 0: the first row is the entry, so its loss is exactly 0
    max_short_loss = max(qty * (r["mark_price"] - entry_mark) for r in rows)

    return {"qty": qty, "funding": funding, "basis": basis, "fees": fees,
            "net": net, "days": days, "annualized": annualized,
            "max_short_loss": max_short_loss}


def split_halves(rows):
    """Split rows in half by count (second half gets the extra row if odd)."""
    middle = len(rows) // 2
    return rows[:middle], rows[middle:]


def evaluate(rows, hurdle=HURDLE, capital=CAPITAL):
    """Full run plus each half, and the pass checks from RULES.md."""
    full = run_strategy_a(rows, capital=capital)
    first_half, second_half = split_halves(rows)
    half1 = run_strategy_a(first_half)
    half2 = run_strategy_a(second_half)
    beats_hurdle = full["annualized"] > hurdle
    both_halves = half1["net"] > 0 and half2["net"] > 0
    return {"full": full, "half1": half1, "half2": half2,
            "beats_hurdle": beats_hurdle, "both_halves": both_halves,
            "passed": beats_hurdle and both_halves}


def funding_stats(rows, baseline=BASELINE_RATE):
    """Average funding per interval, annualized (3 intervals/day), % negative, % at baseline."""
    rates = [r["funding_rate"] for r in rows]
    n = len(rates)
    average = sum(rates) / n
    return {"intervals": n,
            "average": average,
            "annualized": average * 3 * 365,
            "pct_negative": sum(1 for x in rates if x < 0) / n,
            "pct_baseline": sum(1 for x in rates if abs(x - baseline) < 1e-12) / n}


def compare_rates(rows_a, rows_b):
    """On intervals both files have, count how many funding rates are identical."""
    rates_a = {r["interval_start"]: r["funding_rate"] for r in rows_a}
    overlap = [r for r in rows_b if r["interval_start"] in rates_a]
    matches = sum(1 for r in overlap if abs(r["funding_rate"] - rates_a[r["interval_start"]]) < 1e-12)
    return {"overlap": len(overlap), "matches": matches}


def _money(x):
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def print_report(coin, rows):
    result = evaluate(rows)
    stats = funding_stats(rows)
    full = result["full"]
    print("=" * 70)
    print(f"{coin}: {rows[0]['interval_start']} -> {rows[-1]['interval_end']} "
          f"({full['days']:.1f} days, {stats['intervals']} intervals)")
    print(f"  funding: avg {stats['average'] * 100:.4f}% per 8h = {stats['annualized'] * 100:.2f}%/yr "
          f"| negative {stats['pct_negative'] * 100:.1f}% | at 0.01% {stats['pct_baseline'] * 100:.1f}%")
    print(f"  qty {full['qty']:.6f} | funding {_money(full['funding'])} | basis {_money(full['basis'])} "
          f"| fees -{_money(full['fees'])} | NET {_money(full['net'])}")
    print(f"  annualized on ${CAPITAL:,.0f}: {full['annualized'] * 100:.2f}%  (hurdle {HURDLE * 100:.2f}%)")
    print(f"  half 1 net {_money(result['half1']['net'])} | half 2 net {_money(result['half2']['net'])}")
    print(f"  largest short-side loss {_money(full['max_short_loss'])} vs $500 margin")
    print(f"  beats hurdle: {result['beats_hurdle']} | both halves profitable: {result['both_halves']}"
          f"  ->  {'PASS' if result['passed'] else 'FAIL'}")


def main():
    for coin, filename in COINS.items():
        print_report(coin, load_rows(filename))
    print("=" * 70)
    for coin, big, small in COMPARE:
        c = compare_rates(load_rows(big), load_rows(small))
        print(f"{coin} big vs small contract: {c['matches']} of {c['overlap']} overlapping rates identical")


if __name__ == "__main__":
    main()
