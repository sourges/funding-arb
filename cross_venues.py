"""Cross-venue funding logger - the logic (no network, so it can be tested).

Every venue's funding is turned into the same row:
    venue, coin, funding_time, rate, interval_hours, annualized, price
annualized = rate x (24 / interval_hours) x 365   (0.10 = 10%/yr, + = longs pay shorts)

Then gaps: for a coin on 2+ venues, LONG the venue with the lower rate and SHORT
the one with the higher rate; the gap is what that pair collects per year.
"""
import math
from datetime import datetime, timedelta
from itertools import combinations

LOG_FIELDS = ["venue", "coin", "funding_time", "rate", "interval_hours", "annualized", "price"]


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def annualize(rate, interval_hours):
    return rate * (24 / interval_hours) * 365


def clean_coin(name, aliases):
    name = name.strip().upper()
    return aliases.get(name, name)


def make_row(venue, coin, funding_time, rate, interval_hours, price):
    return {"venue": venue, "coin": coin, "funding_time": funding_time,
            "rate": rate, "interval_hours": interval_hours,
            "annualized": annualize(rate, interval_hours), "price": price}


# ---------- Kraken US (Bitnomial) ----------

def bitnomial_rows(coin, parsed_rows):
    """parsed_rows come from fetch_funding.fetch_history (already USD prices)."""
    return [make_row("kraken", coin, r["interval_start"], r["funding_rate"], 8.0, r["mark_price"])
            for r in parsed_rows]


# ---------- Coinbase ----------

def coinbase_rows(products, aliases):
    """Keep products named '... PERP' that carry a funding rate.

    Returns (rows, skipped_names). Skipped = named PERP but no funding rate.
    """
    rows, skipped = [], []
    for p in products:
        name = str(p.get("display_name", ""))
        if not name.upper().endswith(" PERP"):
            continue
        details = p.get("future_product_details") or {}
        rate = details.get("funding_rate")
        interval = str(details.get("funding_interval", ""))
        if rate in (None, "") or not interval.endswith("s") or not details.get("funding_time"):
            skipped.append(name)
            continue
        raw = name[:-len(" PERP")].strip().upper()
        coin = clean_coin(raw, aliases)
        price = _float(p.get("mid_market_price")) or _float(p.get("price"))
        if price is not None and raw.startswith("1000"):
            price = price / 1000          # 1000SHIB price -> price per SHIB
        rows.append(make_row("coinbase", coin, details["funding_time"], float(rate),
                             float(interval[:-1]) / 3600, price))
    return rows, skipped


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------- Kalshi ----------

def kalshi_crypto_markets(markets, crypto_classes, aliases):
    """ticker -> {coin, contract_size} for crypto perps only. KXBTCPERP -> BTC."""
    keep = {}
    for m in markets:
        asset_class = str(m.get("asset_class", "")).lower()
        if not any(word in asset_class for word in crypto_classes):
            continue
        ticker = str(m.get("ticker", ""))
        if not (ticker.startswith("KX") and ticker.endswith("PERP")):
            continue
        coin = clean_coin(ticker[2:-4], aliases)
        size = _float(m.get("contract_size")) or 1.0
        mult = _float(m.get("underlying_multiplier")) or 1.0
        keep[ticker] = {"coin": coin, "contract_size": size * mult}
    return keep


def kalshi_rows(funding_rates, crypto_markets):
    """Kalshi prices are per contract: price per coin = mark / contract_size."""
    rows = []
    for f in funding_rates:
        market = crypto_markets.get(f.get("market_ticker"))
        if market is None:
            continue
        mark = _float(f.get("mark_price"))
        price = mark / market["contract_size"] if mark is not None else None
        rows.append(make_row("kalshi", market["coin"], f["funding_time"],
                             float(f["funding_rate"]), 8.0, price))
    return rows


# ---------- de-dupe ----------

def row_key(row):
    return f"{row['venue']}|{row['coin']}|{row['funding_time']}"


def new_rows_only(rows, seen):
    """Rows not seen before (adds them to seen). Keeps the order given."""
    fresh = []
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen[key] = row["funding_time"]
        fresh.append(row)
    return fresh


def prune_seen(seen, now_utc, keep_days=7):
    """Forget keys older than keep_days so the state file doesn't grow forever."""
    cutoff = now_utc - timedelta(days=keep_days)
    return {k: t for k, t in seen.items() if parse_time(t) >= cutoff}


# ---------- gaps ----------

def latest_by_venue(rows):
    """coin -> venue -> annualized of that venue's most recent row."""
    latest = {}
    for r in rows:
        best = latest.setdefault(r["coin"], {}).get(r["venue"])
        if best is None or r["funding_time"] > best["funding_time"]:
            latest[r["coin"]][r["venue"]] = r
    return {coin: {v: r["annualized"] for v, r in venues.items()} for coin, venues in latest.items()}


def min_rows(hours, interval_hours, min_coverage):
    """How many rows a venue needs in the window to count: 24h of 1h rows at 60% -> 15."""
    return math.ceil(hours / interval_hours * min_coverage)


def average_by_venue(rows, now_utc, hours=24, min_coverage=0.6):
    """coin -> venue -> average annualized over the last `hours`.

    A venue only counts once it covers enough of the window (min_coverage), so one
    Coinbase reading right after startup isn't treated as a 24h average.
    """
    cutoff = now_utc - timedelta(hours=hours)
    sums = {}
    for r in rows:
        if parse_time(r["funding_time"]) < cutoff:
            continue
        total, count, interval = sums.setdefault(r["coin"], {}).get(
            r["venue"], (0.0, 0, r["interval_hours"]))
        sums[r["coin"]][r["venue"]] = (total + r["annualized"], count + 1, interval)
    result = {}
    for coin, venues in sums.items():
        kept = {v: t / c for v, (t, c, i) in venues.items()
                if c >= min_rows(hours, i, min_coverage)}
        if kept:
            result[coin] = kept
    return result


def gaps(by_venue):
    """Every venue pair per coin: long the lower rate, short the higher. Biggest first."""
    result = []
    for coin, venues in by_venue.items():
        for a, b in combinations(sorted(venues), 2):
            low, high = (a, b) if venues[a] <= venues[b] else (b, a)
            result.append({"coin": coin, "long": low, "short": high,
                           "gap": venues[high] - venues[low],
                           "long_rate": venues[low], "short_rate": venues[high]})
    return sorted(result, key=lambda g: g["gap"], reverse=True)


def gap_key(g):
    return f"{g['coin']}|{g['long']}|{g['short']}"


def check_gap_alerts(gap_list, level, reset_factor, alerted):
    """Gaps that newly crossed `level`. `alerted` (a dict) remembers who already got one;
    a key is cleared once its gap drops below level x reset_factor (or the pair vanishes)."""
    fire = []
    current = {gap_key(g): g for g in gap_list}
    for key in list(alerted):
        g = current.get(key)
        if g is None or g["gap"] < level * reset_factor:
            del alerted[key]
    for key, g in current.items():
        if g["gap"] >= level and key not in alerted:
            alerted[key] = True
            fire.append(g)
    return fire


# ---------- messages ----------

def pct(x):
    return f"{x * 100:.1f}%"


def gap_line(g):
    return (f"{g['coin']}: long {g['long']} ({pct(g['long_rate'])}) / short {g['short']} "
            f"({pct(g['short_rate'])}) = {pct(g['gap'])}/yr")


def alert_message(kind, g):
    if kind == "spike":
        return f"⚡ Funding SPIKE gap {gap_line(g)} (latest interval)"
    return f"📈 Steady funding gap {gap_line(g)} (24h average)"


def summary_message(avg_gaps, top, counts):
    lines = ["📊 Cross-venue funding (24h averages, %/yr)"]
    if not avg_gaps:
        lines.append("No coin on 2+ venues yet")
    for g in avg_gaps[:top]:
        lines.append(gap_line(g))
    lines.append("Rows logged last 24h: " + ", ".join(f"{v} {n}" for v, n in sorted(counts.items())))
    return "\n".join(lines)


def record_venue_error(errors, venue, alert_after):
    """errors: venue -> {"count", "alerted"}. True the first time count reaches alert_after."""
    e = errors.setdefault(venue, {"count": 0, "alerted": False})
    e["count"] += 1
    if e["count"] >= alert_after and not e["alerted"]:
        e["alerted"] = True
        return True
    return False


def record_venue_ok(errors, venue):
    """True if this ends an error streak that was alerted."""
    e = errors.setdefault(venue, {"count": 0, "alerted": False})
    recovered = e["alerted"]
    e["count"], e["alerted"] = 0, False
    return recovered


def summary_due(last_date, now_local, hour):
    return now_local.hour >= hour and last_date != now_local.date().isoformat()
