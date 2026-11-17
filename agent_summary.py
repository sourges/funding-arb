"""Daily funding summary for the idea agent: plain numbers, worked out in code.

Reads cross_funding.csv (never writes to it) and writes agent_summary.txt:
  1. top gaps        24h and 7d average gap per coin and venue pair
  2. streaks         days in a row a gap stayed at or above PERSIST_GAP
  3. movers          24h gap now vs the 24h gap one day earlier
  4. flips           pairs whose daily gap changed sign in the last LOOKBACK_DAYS
  5. venue habits    average rate per venue, how often it sits at its usual rate
  6. price context   each coin's 24h and 7d price change
  7. data health     rows, first/last row and missing coins per venue

Coins in summary_settings.EXCLUDE_COINS (stock-index and gold perps) are left out.

It does NOT work out profit, and nothing about the RULES_3 forward test.
A "day" is a UTC calendar day. Only finished days are used (today is left out).

Run: python agent_summary.py
"""
import csv
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import combinations

import cross_settings as cs
import cross_venues as cv
import summary_settings as s


# ---------- reading ----------

def load_rows(path):
    """Every row of the log, numbers as floats. A missing file gives an empty list."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"venue": r["venue"], "coin": r["coin"],
                         "funding_time": r["funding_time"], "rate": float(r["rate"]),
                         "interval_hours": float(r["interval_hours"]),
                         "annualized": float(r["annualized"]),
                         "price": float(r["price"]) if r["price"] else None})
    return rows


def drop_coins(rows, exclude):
    """(rows without the excluded coins, sorted list of excluded coins that were present)."""
    skip = set(exclude)
    kept = [r for r in rows if r["coin"] not in skip]
    dropped = sorted({r["coin"] for r in rows if r["coin"] in skip})
    return kept, dropped


# ---------- daily averages and daily gaps ----------

def daily_averages(rows, today, min_coverage=0.6):
    """coin -> venue -> {date: average annualized} for finished UTC days (before `today`).

    A day counts only if the venue logged enough of it (24 hourly rows at 60% -> 15).
    """
    buckets = {}
    for r in rows:
        day = cv.parse_time(r["funding_time"]).date()
        if day >= today:
            continue
        buckets.setdefault((r["coin"], r["venue"], day), []).append(r)
    result = {}
    for (coin, venue, day), day_rows in buckets.items():
        need = cv.min_rows(24, day_rows[0]["interval_hours"], min_coverage)
        if len(day_rows) < need:
            continue
        avg = sum(r["annualized"] for r in day_rows) / len(day_rows)
        result.setdefault(coin, {}).setdefault(venue, {})[day] = avg
    return result


def pair_daily_gaps(daily):
    """(coin, a, b) -> {date: b's average minus a's}, a before b in the alphabet.

    Only days where BOTH venues have an average. + means b pays more (short b, long a).
    """
    result = {}
    for coin, venues in daily.items():
        for a, b in combinations(sorted(venues), 2):
            shared = sorted(set(venues[a]) & set(venues[b]))
            if shared:
                result[(coin, a, b)] = {d: venues[b][d] - venues[a][d] for d in shared}
    return result


def streaks(pair_gaps, level, last_day):
    """Days in a row, ending on `last_day`, with the gap at or above `level` the same way.

    A missing day or a day under the level ends the streak. Longest first.
    """
    result = []
    for (coin, a, b), by_day in pair_gaps.items():
        latest = by_day.get(last_day)
        if latest is None or abs(latest) < level:
            continue
        sign = 1 if latest > 0 else -1
        days, day = 0, last_day
        while day in by_day and by_day[day] * sign >= level:
            days += 1
            day -= timedelta(days=1)
        long_v, short_v = (a, b) if sign > 0 else (b, a)
        result.append({"coin": coin, "long": long_v, "short": short_v,
                       "days": days, "latest_gap": abs(latest)})
    return sorted(result, key=lambda x: (-x["days"], -x["latest_gap"], x["coin"]))


def flips(pair_gaps, first_day, last_day):
    """Pairs whose daily gap changed sign between first_day and last_day (both included).

    A day with a gap of exactly 0 is skipped. Most flips first.
    """
    result = []
    for (coin, a, b), by_day in pair_gaps.items():
        signs = [1 if g > 0 else -1 for d, g in sorted(by_day.items())
                 if first_day <= d <= last_day and g != 0]
        count = sum(1 for x, y in zip(signs, signs[1:]) if x != y)
        if count:
            result.append({"coin": coin, "a": a, "b": b, "flips": count, "days": len(signs)})
    return sorted(result, key=lambda x: (-x["flips"], x["coin"], x["a"], x["b"]))


# ---------- movers ----------

def movers(rows, now_utc, min_coverage=0.6, stale_hours=48):
    """24h gap now vs the 24h gap one day earlier, for pairs that have both.

    The pair is pointed the way it earns NOW (long the lower rate), and the older gap
    is measured the same way, so a negative `before` means the pair flipped.
    Biggest change first.
    """
    earlier = now_utc - timedelta(hours=24)
    now_avg = cv.average_by_venue(rows, now_utc, min_coverage=min_coverage,
                                  stale_hours=stale_hours)
    old_rows = [r for r in rows if cv.parse_time(r["funding_time"]) <= earlier]
    old_avg = cv.average_by_venue(old_rows, earlier, min_coverage=min_coverage,
                                  stale_hours=stale_hours)
    result = []
    for g in cv.gaps(now_avg):
        old = old_avg.get(g["coin"], {})
        if g["long"] not in old or g["short"] not in old:
            continue
        before = old[g["short"]] - old[g["long"]]
        result.append({"coin": g["coin"], "long": g["long"], "short": g["short"],
                       "now": g["gap"], "before": before, "change": g["gap"] - before})
    return sorted(result, key=lambda x: (-abs(x["change"]), x["coin"]))


# ---------- venue habits ----------

def venue_habits(rows, now_utc, days=7):
    """Per venue over the last `days`: rows, coins, average yearly rate, and the share
    of rows sitting exactly at that venue's most common rate."""
    cutoff = now_utc - timedelta(days=days)
    by_venue = {}
    for r in rows:
        if cv.parse_time(r["funding_time"]) >= cutoff:
            by_venue.setdefault(r["venue"], []).append(r)
    result = {}
    for venue, vrows in by_venue.items():
        usual, count = Counter(r["rate"] for r in vrows).most_common(1)[0]
        result[venue] = {"rows": len(vrows), "coins": len({r["coin"] for r in vrows}),
                         "average": sum(r["annualized"] for r in vrows) / len(vrows),
                         "usual_rate": usual, "usual_share": count / len(vrows)}
    return result


# ---------- price context ----------

def _price_at(priced, target, slack_hours):
    """Price of the newest row at or before `target`, if it isn't more than slack older."""
    best = None
    for t, price in priced:
        if t <= target:
            best = (t, price)
    if best is None or best[0] < target - timedelta(hours=slack_hours):
        return None
    return best[1]


def price_changes(rows, venues, slack_hours=9):
    """coin -> {venue, price, change_24h, change_7d}, from the first venue in `venues`
    that has prices for the coin. A change is None when there's no row old enough
    (or the nearest one is more than slack_hours away from the target time)."""
    priced = {}
    for r in rows:
        if r["price"]:
            priced.setdefault(r["coin"], {}).setdefault(r["venue"], []).append(
                (cv.parse_time(r["funding_time"]), r["price"]))
    result = {}
    for coin, by_venue in priced.items():
        venue = next((v for v in venues if v in by_venue), None)
        if venue is None:
            continue
        series = sorted(by_venue[venue])
        newest_time, newest = series[-1]
        entry = {"venue": venue, "price": newest}
        for name, hours in (("change_24h", 24), ("change_7d", 168)):
            old = _price_at(series, newest_time - timedelta(hours=hours), slack_hours)
            entry[name] = newest / old - 1 if old else None
        result[coin] = entry
    return result


# ---------- data health ----------

def data_health(rows, now_utc, days=7):
    """Per venue: total rows, first and last funding time, rows in the last 24h, and
    coins seen in the last `days` that logged nothing in the last 24h."""
    day_ago = now_utc - timedelta(hours=24)
    week_ago = now_utc - timedelta(days=days)
    result = {}
    for r in rows:
        t = cv.parse_time(r["funding_time"])
        v = result.setdefault(r["venue"], {"rows": 0, "first": t, "last": t, "rows_24h": 0,
                                           "recent": set(), "today": set()})
        v["rows"] += 1
        v["first"], v["last"] = min(v["first"], t), max(v["last"], t)
        if t >= week_ago:
            v["recent"].add(r["coin"])
        if t >= day_ago:
            v["rows_24h"] += 1
            v["today"].add(r["coin"])
    for v in result.values():
        v["missing"] = sorted(v.pop("recent") - v.pop("today"))
    return result


# ---------- text ----------

def signed(x):
    return f"{x * 100:+.1f}%"


def build_text(rows, now_utc):
    today = now_utc.date()
    last_day = today - timedelta(days=1)
    first_day = today - timedelta(days=s.LOOKBACK_DAYS)
    out = [f"FUNDING SUMMARY {now_utc:%Y-%m-%d %H:%M} UTC",
           "Rates are yearly %. + means longs pay shorts. A gap = short venue minus long venue.",
           "Days are UTC days; today is not finished, so it is left out of streaks and flips."]
    rows, dropped = drop_coins(rows, s.EXCLUDE_COINS)
    if dropped:
        out.append(f"Left out (not crypto): {', '.join(dropped)}")
    if not rows:
        return "\n".join(out + ["", "NO DATA: cross_funding.csv is missing or empty."])

    health = data_health(rows, now_utc, s.LOOKBACK_DAYS)
    first = min(v["first"] for v in health.values())
    span = (now_utc - first).total_seconds() / 86400
    out.append(f"Data starts {first:%Y-%m-%d %H:%M} UTC: {span:.1f} days. "
               "Treat any pattern from under 30 days as weak.")

    for title, hours in (("1. TOP GAPS, 24h average", 24),
                         (f"1b. TOP GAPS, {s.LOOKBACK_DAYS}d average", 24 * s.LOOKBACK_DAYS)):
        out += ["", title]
        gap_list = cv.gaps(cv.average_by_venue(rows, now_utc, hours=hours,
                                               min_coverage=s.MIN_COVERAGE,
                                               stale_hours=s.STALE_HOURS))
        out += [cv.gap_line(g) for g in gap_list[:s.TOP]] or ["none (not enough rows yet)"]
        out.append(f"({len(gap_list)} pairs in total)")

    pair_gaps = pair_daily_gaps(daily_averages(rows, today, s.MIN_COVERAGE))

    out += ["", f"2. STREAKS: days in a row at or above {cv.pct(s.PERSIST_GAP)}/yr, "
                f"ending {last_day}"]
    streak_list = streaks(pair_gaps, s.PERSIST_GAP, last_day)
    out += [f"{x['coin']}: long {x['long']} / short {x['short']}: {x['days']} days, "
            f"latest day {cv.pct(x['latest_gap'])}" for x in streak_list[:s.TOP]] or ["none"]

    out += ["", "3. MOVERS: 24h gap now vs one day earlier"]
    mover_list = movers(rows, now_utc, s.MIN_COVERAGE, s.STALE_HOURS)
    out += [f"{x['coin']}: long {x['long']} / short {x['short']}: {signed(x['before'])} -> "
            f"{signed(x['now'])} (change {signed(x['change'])})"
            for x in mover_list[:s.TOP]] or ["none (needs two days of rows)"]

    out += ["", f"4. FLIPS: daily gap changed sign, {first_day} to {last_day}"]
    flip_list = flips(pair_gaps, first_day, last_day)
    out += [f"{x['coin']}: {x['a']} vs {x['b']}: {x['flips']} flips in {x['days']} days"
            for x in flip_list[:s.TOP]] or ["none"]

    out += ["", f"5. VENUE HABITS, last {s.LOOKBACK_DAYS} days"]
    habits = venue_habits(rows, now_utc, s.LOOKBACK_DAYS)
    for venue in sorted(habits):
        h = habits[venue]
        out.append(f"{venue}: average {signed(h['average'])}/yr over {h['rows']} rows, "
                   f"{h['coins']} coins; {h['usual_share'] * 100:.0f}% of rows at its usual "
                   f"rate of {h['usual_rate'] * 100:.4f}% per interval")

    out += ["", "6. PRICE CONTEXT (24h / 7d change)"]
    prices = price_changes(rows, s.PRICE_VENUES)
    for coin in sorted(prices):
        p = prices[coin]
        d1 = signed(p["change_24h"]) if p["change_24h"] is not None else "n/a"
        d7 = signed(p["change_7d"]) if p["change_7d"] is not None else "n/a"
        out.append(f"{coin}: {d1} / {d7} ({p['venue']})")

    out += ["", "7. DATA HEALTH"]
    for venue in sorted(health):
        v = health[venue]
        age = (now_utc - v["last"]).total_seconds() / 3600
        line = (f"{venue}: {v['rows']} rows since {v['first']:%Y-%m-%d}, {v['rows_24h']} in "
                f"the last 24h, newest row {age:.1f}h old")
        if v["missing"]:
            line += f"; no rows in 24h for: {', '.join(v['missing'])}"
        out.append(line)
    return "\n".join(out)


def main():
    now = datetime.now(timezone.utc)
    text = build_text(load_rows(cs.LOG_FILE), now)
    with open(s.SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nSaved to {s.SUMMARY_FILE}")


if __name__ == "__main__":
    main()
