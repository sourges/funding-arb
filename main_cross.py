"""Cross-venue funding logger: Kraken US (Bitnomial), Coinbase US perps, Kalshi perps.

Every CHECK_MINUTES (hourly):
  1. fetch funding from all three venues -> one row per venue/coin/funding time
  2. append only NEW rows to cross_funding.csv
  3. gap alerts: steady (24h average >= 15%/yr) and spike (latest >= 100%/yr)
  4. once a day at SUMMARY_HOUR -> Telegram summary of the biggest gaps
A venue that fails is skipped for that check; the others still log.
Places NO orders, needs no exchange keys. Safe to restart.

Run: python main_cross.py   (or start_cross.bat). Ctrl+C to stop.
"""
import asyncio
import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from telegram import Bot
from telegram.request import HTTPXRequest

import cross_settings as s
import cross_venues as cv
import fetch_funding as ff
from telegram_send import send_with_retries

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

COINBASE_URL = "https://api.coinbase.com/api/v3/brokerage/market/products"
KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2"


# ---------- venue fetchers (network) ----------

def get_json(url, params):
    r = requests.get(url, params=params, timeout=s.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_kraken(increments, since_iso):
    rows = []
    for coin, base in s.BITNOMIAL_COINS.items():
        if coin not in increments:
            increments[coin] = ff.get_price_increment(base)
        parsed = ff.fetch_history(base, since_iso, increments[coin])
        rows.extend(cv.bitnomial_rows(coin, parsed))
    return rows


def fetch_coinbase():
    """Coinbase pages with a cursor: pagination.has_next / next_cursor."""
    products = {}
    params = {"product_type": "FUTURE", "limit": 1000}
    for _ in range(20):                     # page guard
        page = get_json(COINBASE_URL, dict(params))
        added = 0
        for p in page.get("products", []):
            if p.get("product_id") not in products:
                products[p.get("product_id")] = p
                added += 1
        pagination = page.get("pagination") or {}
        if not pagination.get("has_next") or not pagination.get("next_cursor") or added == 0:
            break
        params["cursor"] = pagination["next_cursor"]
    products = list(products.values())
    rows, skipped = cv.coinbase_rows(products, s.ALIASES)
    return rows, skipped, len(products)


def fetch_kalshi(since_ts):
    markets = get_json(KALSHI_URL + "/margin/markets", {"status": "active"}).get("markets", [])
    crypto = cv.kalshi_crypto_markets(markets, s.KALSHI_CRYPTO_CLASSES, s.ALIASES)
    history = get_json(KALSHI_URL + "/margin/funding_rates/historical",
                       {"start_ts": since_ts}).get("funding_rates", [])
    classes = sorted({str(m.get("asset_class", "")) for m in markets})
    return cv.kalshi_rows(history, crypto), len(crypto), classes


# ---------- files ----------

def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"seen": {}, "steady_alerted": {}, "spike_alerted": {},
                "errors": {}, "last_summary_date": None}


def save_state(state, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(1)
    os.replace(tmp, path)


def append_rows(rows, path):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cv.LOG_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def load_recent(path, now_utc, hours=72):
    """Rows from the CSV within the last `hours` (for 24h averages after a restart)."""
    if not os.path.exists(path):
        return []
    cutoff = now_utc - timedelta(hours=hours)
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if cv.parse_time(r["funding_time"]) < cutoff:
                continue
            rows.append({"venue": r["venue"], "coin": r["coin"], "funding_time": r["funding_time"],
                         "rate": float(r["rate"]), "interval_hours": float(r["interval_hours"]),
                         "annualized": float(r["annualized"]),
                         "price": float(r["price"]) if r["price"] else None})
    return rows


def log_error(line):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ERROR] {line}")
    try:
        with open(s.ERRORS_FILE, "a") as f:
            f.write(f"{stamp} {line}\n")
    except OSError:
        pass


# ---------- main loop ----------

async def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
        return
    telegram = Bot(token=TELEGRAM_TOKEN,
                   request=HTTPXRequest(connect_timeout=30, read_timeout=30,
                                        write_timeout=30, pool_timeout=30))

    async def alert(message):
        print(f"[TELEGRAM] {message}")
        await send_with_retries(lambda m: telegram.send_message(chat_id=CHAT_ID, text=m),
                                message, log=log_error)

    state = load_state(s.STATE_FILE)
    recent = load_recent(s.LOG_FILE, datetime.now(timezone.utc))
    increments = {}
    first_check = True
    await alert(f"▶️ Cross-venue funding logger started ({len(recent)} recent rows loaded)")

    while True:
        now = datetime.now(timezone.utc)
        since_iso = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since_ts = int((now - timedelta(days=2)).timestamp())
        all_rows, status = [], []

        venues = [("kraken", lambda: (fetch_kraken(increments, since_iso),)),
                  ("coinbase", fetch_coinbase),
                  ("kalshi", lambda: fetch_kalshi(since_ts))]
        for venue, fetch in venues:
            try:
                result = fetch()
                rows = result[0]
                all_rows.extend(rows)
                if venue == "coinbase":
                    status.append(f"coinbase {len(rows)} perps of {result[2]} products")
                    if first_check and result[1]:
                        print(f"Coinbase PERPs with no funding rate (skipped): {result[1]}")
                elif venue == "kalshi":
                    status.append(f"kalshi {result[1]} crypto perps")
                    if first_check:
                        print(f"Kalshi asset classes seen: {result[2]}")
                else:
                    status.append(f"kraken {len(rows)} rows")
                if cv.record_venue_ok(state["errors"], venue):
                    await alert(f"✅ Cross logger: {venue} working again")
            except Exception as e:
                log_error(f"{venue} failed: {e!r}")
                if cv.record_venue_error(state["errors"], venue, s.ERROR_ALERT_AFTER):
                    await alert(f"⚠️ Cross logger: {venue} failed {s.ERROR_ALERT_AFTER} checks "
                                f"in a row. Last error: {e!r}")

        fresh = cv.new_rows_only(all_rows, state["seen"])
        if fresh:
            append_rows(fresh, s.LOG_FILE)
            recent.extend(fresh)
        cutoff = now - timedelta(hours=72)
        recent = [r for r in recent if cv.parse_time(r["funding_time"]) >= cutoff]
        state["seen"] = cv.prune_seen(state["seen"], now)

        avg_gaps = cv.gaps(cv.average_by_venue(recent, now, min_coverage=s.MIN_COVERAGE,
                                                stale_hours=s.STALE_HOURS))
        latest_gaps = cv.gaps(cv.latest_by_venue(recent, now, stale_hours=s.STALE_HOURS))
        for g in cv.check_gap_alerts(avg_gaps, s.STEADY_GAP, s.RESET_FACTOR, state["steady_alerted"]):
            await alert(cv.alert_message("steady", g))
        for g in cv.check_gap_alerts(latest_gaps, s.SPIKE_GAP, s.RESET_FACTOR, state["spike_alerted"]):
            await alert(cv.alert_message("spike", g))

        now_local = datetime.now()
        if cv.summary_due(state["last_summary_date"], now_local, s.SUMMARY_HOUR):
            counts = {}
            for r in recent:
                if cv.parse_time(r["funding_time"]) >= now - timedelta(hours=24):
                    counts[r["venue"]] = counts.get(r["venue"], 0) + 1
            await alert(cv.summary_message(avg_gaps, s.SUMMARY_TOP, counts))
            state["last_summary_date"] = now_local.date().isoformat()

        top = cv.gap_line(avg_gaps[0]) if avg_gaps else "no pairs yet"
        print(f"{now_local:%H:%M} new rows {len(fresh)} | {' | '.join(status)} | top 24h gap: {top}")
        save_state(state, s.STATE_FILE)
        first_check = False
        await asyncio.sleep(s.CHECK_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())
