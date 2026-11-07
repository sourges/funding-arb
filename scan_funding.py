"""Scan: is funding on any Kraken US (Bitnomial) perp NOT stuck at 0.01%?

Run after `python fetch_funding.py --scan`:
    python scan_funding.py
Prints one line per coin, sorted by average funding (highest first).

This is a SCAN to decide what to log going forward, not a strategy test:
the coin that looks best here is partly luck.
"""
import glob
import os

import backtest as bt
import settings


def summarize(coin, rows):
    """Funding facts for one coin's rows (oldest -> newest)."""
    stats = bt.funding_stats(rows)
    rates = [r["funding_rate"] for r in rows]
    return {"coin": coin,
            "first": rows[0]["interval_start"][:10],
            "intervals": stats["intervals"],
            "annualized": stats["annualized"],
            "pct_baseline": stats["pct_baseline"],
            "pct_negative": stats["pct_negative"],
            "max_rate": max(rates),
            "min_rate": min(rates)}


def coin_from_filename(path):
    """data/scan/funding_SOL.csv -> SOL"""
    name = os.path.splitext(os.path.basename(path))[0]
    return name[len("funding_"):]


def scan(folder):
    results = []
    for path in sorted(glob.glob(os.path.join(folder, "funding_*.csv"))):
        rows = bt.load_rows(path)
        if rows:
            results.append(summarize(coin_from_filename(path), rows))
    return sorted(results, key=lambda r: r["annualized"], reverse=True)


def main():
    results = scan(settings.SCAN_DIR)
    if not results:
        print(f"No CSVs in {settings.SCAN_DIR} - run: python fetch_funding.py --scan")
        return
    print(f"{'coin':<6}{'since':<12}{'intervals':>10}{'avg/yr':>9}{'at 0.01%':>10}"
          f"{'negative':>10}{'max':>10}{'min':>10}")
    for r in results:
        print(f"{r['coin']:<6}{r['first']:<12}{r['intervals']:>10}{r['annualized'] * 100:>8.2f}%"
              f"{r['pct_baseline'] * 100:>9.1f}%{r['pct_negative'] * 100:>9.1f}%"
              f"{r['max_rate'] * 100:>9.4f}%{r['min_rate'] * 100:>9.4f}%")


if __name__ == "__main__":
    main()
