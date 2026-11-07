"""Backtest 2 - Strategy A with $740 margin, exactly as locked in RULES_2.md.

Run:  python backtest_2.py
Reuses Backtest 1's math (backtest.py); only margin, capital and the
no-liquidation check are new.
"""
import backtest as bt

# ---- locked in RULES_2.md (do not tune) ----
MARGIN = 740.0
CAPITAL = 1000.0 + MARGIN          # $1,740
MAINT_RATE = {"BTC": 0.161, "ETH": 0.157}   # Kraken contract specs, Nov 6 2026


def liquidation_check(rows, qty, entry_mark, margin, maint_rate):
    """Walk every row: equity = margin - short loss; liquidated if equity < maintenance.

    Returns liquidated (bool), first liquidation interval_start (or None),
    and the smallest cushion (equity - maintenance) seen.
    """
    first_liquidation = None
    min_cushion = None
    for r in rows:
        equity = margin - qty * (r["mark_price"] - entry_mark)
        maintenance = maint_rate * qty * r["mark_price"]
        cushion = equity - maintenance
        if min_cushion is None or cushion < min_cushion:
            min_cushion = cushion
        if cushion < 0 and first_liquidation is None:
            first_liquidation = r["interval_start"]
    return {"liquidated": first_liquidation is not None,
            "first_liquidation": first_liquidation,
            "min_cushion": min_cushion}


def evaluate_2(rows, maint_rate, hurdle=bt.HURDLE, margin=MARGIN, capital=CAPITAL):
    """Backtest 1 checks on $1,740 capital, plus never liquidated."""
    result = bt.evaluate(rows, hurdle=hurdle, capital=capital)
    full = result["full"]
    liq = liquidation_check(rows, full["qty"], rows[0]["mark_price"], margin, maint_rate)
    result["liquidation"] = liq
    result["passed"] = result["beats_hurdle"] and result["both_halves"] and not liq["liquidated"]
    return result


def print_report(coin, rows):
    result = evaluate_2(rows, MAINT_RATE[coin])
    full, liq = result["full"], result["liquidation"]
    print("=" * 70)
    print(f"{coin}: {full['days']:.1f} days | NET {bt._money(full['net'])} "
          f"(funding {bt._money(full['funding'])}, basis {bt._money(full['basis'])}, "
          f"fees -{bt._money(full['fees'])})")
    print(f"  annualized on ${CAPITAL:,.0f}: {full['annualized'] * 100:.2f}%  (hurdle {bt.HURDLE * 100:.2f}%)")
    print(f"  half 1 net {bt._money(result['half1']['net'])} | half 2 net {bt._money(result['half2']['net'])}")
    print(f"  margin ${MARGIN:,.0f}, maintenance {MAINT_RATE[coin] * 100:.1f}% | "
          f"smallest cushion {bt._money(liq['min_cushion'])} | "
          f"liquidated: {liq['first_liquidation'] or 'never'}")
    print(f"  beats hurdle: {result['beats_hurdle']} | both halves: {result['both_halves']} | "
          f"not liquidated: {not liq['liquidated']}  ->  {'PASS' if result['passed'] else 'FAIL'}")


def main():
    for coin, filename in bt.COINS.items():
        print_report(coin, bt.load_rows(filename))
    print("=" * 70)


if __name__ == "__main__":
    main()
