"""ETH funding monitor (paper): logs live funding for a pretend arb position and
sends Telegram alerts. Places NO orders, needs no Kraken keys.

Every CHECK_MINUTES:
  1. fetch new funding intervals from Bitnomial -> add paper funding, log to CSV
  2. read Kraken's ETH/USD spot price -> margin cushion check
  3. once a day at SUMMARY_HOUR -> Telegram summary
Safe to restart: everything is saved in monitor_state.json.

Run: python main_monitor.py   (or start_monitor.bat). Ctrl+C to stop.
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

import fetch_funding as ff
import monitor
import monitor_settings as s
from telegram_send import send_with_retries

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LOG_FIELDS = ["interval_start", "funding_rate", "mark_price", "funding_earned", "total_funding"]


def kraken_price(pair):
    """Last trade price from Kraken's public ticker (no key)."""
    r = requests.get("https://api.kraken.com/0/public/Ticker", params={"pair": pair},
                     timeout=s.REQUEST_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"Kraken ticker error: {body['error']}")
    ticker = next(iter(body["result"].values()))
    return float(ticker["c"][0])


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_state(state, path):
    """Write to a temp file, then swap it in (a crash mid-write can't corrupt it).
    Retries a few times in case Windows briefly locks the file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(1)
    os.replace(tmp, path)


def append_log(rows, path):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def log_error(line):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ERROR] {line}")
    try:
        with open(s.ERRORS_FILE, "a") as f:
            f.write(f"{stamp} {line}\n")
    except OSError:
        pass


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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

    increment = ff.get_price_increment(s.BASE_SYMBOL)
    state = load_state(s.STATE_FILE)
    if state is None:
        since = iso(datetime.now(timezone.utc) - timedelta(days=2))
        rows = ff.fetch_history(s.BASE_SYMBOL, since, increment)
        if not rows:
            print("❌ No funding rows from Bitnomial - check BASE_SYMBOL")
            return
        state = monitor.new_state(rows[-1], s.NOTIONAL)
        save_state(state, s.STATE_FILE)
        await alert(f"▶️ ETH funding monitor started (paper). Entry mark ${state['entry_mark']:,.2f}, "
                    f"qty {state['qty']:.6f} ETH, margin ${s.MARGIN:,.0f}")
    else:
        print(f"Resuming: {state['intervals']} intervals logged, last {state['last_interval']}")

    while True:
        try:
            rows = ff.fetch_history(s.BASE_SYMBOL, state["last_interval"], increment)
            log_rows, events = monitor.process_rows(state, rows, s.BASELINE_RATE)
            if log_rows:
                append_log(log_rows, s.LOG_FILE)
            for event in events:
                await alert(monitor.event_message(event))

            price = kraken_price(s.KRAKEN_PAIR)
            value = monitor.cushion(state, price, s.MARGIN, s.MAINT_RATE)
            kind = monitor.check_cushion(state, value, s.CUSHION_ALERT, s.CUSHION_RESET)
            if kind:
                await alert(monitor.cushion_message(kind, value, price))

            now_local = datetime.now()
            if monitor.summary_due(state, now_local, s.SUMMARY_HOUR):
                await alert(monitor.summary_message(state, price, value,
                                                    datetime.now(timezone.utc), s.BASELINE_RATE))
                state["last_summary_date"] = now_local.date().isoformat()

            if monitor.record_success(state):
                await alert("✅ ETH funding monitor: checks working again")
            print(f"{now_local:%H:%M} ETH ${price:,.2f} | cushion ${value:,.2f} | "
                  f"paper funding ${state['total_funding']:,.2f} ({state['intervals']} intervals)")
        except Exception as e:
            log_error(f"check failed: {e!r}")
            if monitor.record_error(state, s.ERROR_ALERT_AFTER):
                await alert(f"⚠️ ETH funding monitor: {s.ERROR_ALERT_AFTER} checks in a row failed. "
                            f"Last error: {e!r}")
        save_state(state, s.STATE_FILE)
        await asyncio.sleep(s.CHECK_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())
