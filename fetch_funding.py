"""Fetch funding-rate history for Kraken US perps (listed on Bitnomial) into CSVs.

Usage:
    python fetch_funding.py --list     show active Bitnomial perps and their base symbols
    python fetch_funding.py            fetch every coin in settings.COINS -> data/funding_<COIN>.csv

Each CSV row is one 8-hour funding interval. funding_rate is a decimal:
0.0001 = 0.01% for that interval; positive = longs pay shorts.

The API gives prices in ticks; USD price = ticks x price_increment (from the product spec).
"""
import csv
import os
import sys
from urllib.parse import unquote

import requests

import settings

CSV_FIELDS = ["interval_start", "interval_end", "funding_rate",
              "mark_price", "price_index", "product_id"]


def http_get(path, params):
    """Real HTTP GET against the Bitnomial API. Returns the parsed JSON."""
    url = settings.BASE_URL.rstrip("/") + path
    response = requests.get(url, params=params, timeout=settings.REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _to_float(value):
    """Numbers may come back as strings; missing values become None."""
    if value is None or value == "":
        return None
    return float(value)


def _ticks_to_usd(value, price_increment):
    ticks = _to_float(value)
    if ticks is None:
        return None
    return ticks * price_increment


def parse_row(raw, price_increment=1.0):
    """Turn one API funding row into a flat dict. Prices converted from ticks to USD."""
    return {
        "interval_start": raw["interval_start"],
        "interval_end": raw.get("interval_end", ""),
        "funding_rate": _to_float(raw["funding_rate"]),
        "mark_price": _ticks_to_usd(raw.get("mark_price"), price_increment),
        "price_index": _ticks_to_usd(raw.get("price_index"), price_increment),
        "product_id": raw.get("product_id", ""),
    }


def _spec_list(page):
    """/product/specs/ returns a plain list; tolerate a {"data": [...]} wrapper too."""
    if isinstance(page, dict):
        return page.get("data") or []
    return page or []


def get_price_increment(base_symbol, get=http_get):
    """Look up the perp's price_increment (USD per tick) from its product spec."""
    specs = _spec_list(get(settings.SPECS_PATH, {"base_symbol": base_symbol}))
    for spec in specs:
        if spec.get("type") == "perpetual" and spec.get("price_increment") is not None:
            return float(spec["price_increment"])
    raise ValueError(f"no perpetual spec with price_increment for {base_symbol}")


def fetch_history(base_symbol, begin_time, price_increment=1.0, get=http_get, limit=None):
    """Page through funding rates oldest-first and return parsed rows.

    Stops when a page is empty, has no cursor, or repeats the last cursor
    (guards against looping forever). The API returns the cursor already
    URL-encoded, so it is decoded before being sent back (requests encodes it
    again). Rows are de-duplicated by interval_start and sorted oldest -> newest.
    """
    if limit is None:
        limit = settings.PAGE_LIMIT
    params = {"base_symbol": base_symbol, "begin_time": begin_time,
              "order": "asc", "limit": limit}
    by_start = {}
    last_cursor = None

    while True:
        page = get(settings.FUNDING_PATH, dict(params))
        data = page.get("data") or []
        for raw in data:
            row = parse_row(raw, price_increment)
            by_start[row["interval_start"]] = row

        cursor = (page.get("pagination") or {}).get("cursor")
        if not data or not cursor or cursor == last_cursor:
            break
        last_cursor = cursor
        params["cursor"] = unquote(cursor)

    return [by_start[key] for key in sorted(by_start)]


def write_csv(rows, filename):
    """Write rows to a CSV with a fixed header. Creates the folder if needed."""
    folder = os.path.dirname(filename)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def find_perps(specs):
    """From /product/specs/ rows, keep the ones that look like perpetuals."""
    perps = []
    for spec in specs:
        text = f"{spec.get('product_name', '')} {spec.get('symbol', '')}".lower()
        if spec.get("type") == "perpetual" or "perp" in text:
            perps.append(spec)
    return perps


def list_perps(get=http_get):
    """Print active perps so you can copy base symbols into settings.COINS."""
    specs = _spec_list(get(settings.SPECS_PATH, {"active": "true"}))
    perps = find_perps(specs)
    if not perps:
        print("No perpetuals found - showing all active products:")
        perps = specs
    print(f"{'symbol':<14}{'base_symbol':<14}{'contract_size':<16}name")
    for spec in perps:
        size = f"{spec.get('contract_size', '')} {spec.get('contract_size_unit', '')}"
        print(f"{str(spec.get('symbol', '')):<14}{str(spec.get('base_symbol', '')):<14}"
              f"{size:<16}{spec.get('product_name', '')}")


def fetch_all(coins, begin_time, data_dir, get=http_get):
    """Fetch every coin and write data/funding_<COIN>.csv. Returns {coin: row_count}."""
    counts = {}
    for coin, base_symbol in coins.items():
        if not base_symbol:
            print(f"{coin}: no base_symbol in settings.COINS - skipped (run --list)")
            continue
        increment = get_price_increment(base_symbol, get=get)
        rows = fetch_history(base_symbol, begin_time, increment, get=get)
        counts[coin] = len(rows)
        if not rows:
            print(f"{coin} ({base_symbol}): no funding rows - check the base symbol")
            continue
        filename = os.path.join(data_dir, f"funding_{coin}.csv")
        write_csv(rows, filename)
        print(f"{coin} ({base_symbol}): {len(rows)} rows, "
              f"{rows[0]['interval_start']} -> {rows[-1]['interval_start']}, "
              f"last mark ${rows[-1]['mark_price']:,.2f} -> {filename}")
    return counts


def main(argv):
    if "--list" in argv:
        list_perps()
    else:
        fetch_all(settings.COINS, settings.BEGIN_TIME, settings.DATA_DIR)


if __name__ == "__main__":
    main(sys.argv[1:])
