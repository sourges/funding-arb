"""ETH funding monitor - the logic (no network, no Telegram, so it can be tested).

The monitor holds a PRETEND position: $1,000 of ETH on spot + the same qty short
on the perp, $740 margin. It places no orders. main_monitor.py does the I/O.
"""
from datetime import datetime, timedelta

INTERVAL = timedelta(hours=8)


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def new_state(entry_row, notional):
    """Open the pretend position at the END of entry_row's interval.

    entry_row's own funding is NOT counted (we weren't holding during it).
    """
    return {
        "qty": notional / entry_row["price_index"],
        "entry_mark": entry_row["mark_price"],
        "entry_index": entry_row["price_index"],
        "start_interval": entry_row["interval_start"],
        "last_interval": entry_row["interval_start"],
        "total_funding": 0.0,
        "intervals": 0,
        "off_baseline": 0,
        "gaps": 0,
        "cushion_alerted": False,
        "last_summary_date": None,
        "consecutive_errors": 0,
        "error_alerted": False,
    }


def cushion(state, price, margin, maint_rate):
    """Equity left on the short minus maintenance margin. Below 0 = liquidated."""
    equity = margin - state["qty"] * (price - state["entry_mark"])
    return equity - maint_rate * state["qty"] * price


def process_rows(state, rows, baseline):
    """Add funding for every row newer than state['last_interval'].

    Returns (log_rows, events). Events: ("off_baseline", row) when the rate
    isn't the baseline; ("gap", missing_count) when intervals were skipped.
    Rows are expected oldest -> newest (fetch_history sorts them).
    """
    log_rows, events = [], []
    for row in rows:
        if row["interval_start"] <= state["last_interval"]:
            continue
        missing = round((parse_time(row["interval_start"])
                         - parse_time(state["last_interval"])) / INTERVAL) - 1
        if missing > 0:
            state["gaps"] += missing
            events.append(("gap", missing))

        earned = row["funding_rate"] * state["qty"] * row["mark_price"]
        state["total_funding"] += earned
        state["intervals"] += 1
        state["last_interval"] = row["interval_start"]
        if abs(row["funding_rate"] - baseline) > 1e-12:
            state["off_baseline"] += 1
            events.append(("off_baseline", row))

        log_rows.append({"interval_start": row["interval_start"],
                         "funding_rate": row["funding_rate"],
                         "mark_price": row["mark_price"],
                         "funding_earned": earned,
                         "total_funding": state["total_funding"]})
    return log_rows, events


def check_cushion(state, value, alert_below, reset_above):
    """One alert when the cushion drops below alert_below; one 'OK' once it's
    back above reset_above (the gap stops alerts flapping). Returns 'low', 'ok' or None."""
    if not state["cushion_alerted"] and value < alert_below:
        state["cushion_alerted"] = True
        return "low"
    if state["cushion_alerted"] and value > reset_above:
        state["cushion_alerted"] = False
        return "ok"
    return None


def summary_due(state, now_local, summary_hour):
    """True once per day, at or after summary_hour on the PC's clock."""
    today = now_local.date().isoformat()
    return now_local.hour >= summary_hour and state["last_summary_date"] != today


def record_error(state, alert_after):
    """Count a failed check. Returns True the first time the count reaches alert_after."""
    state["consecutive_errors"] += 1
    if state["consecutive_errors"] >= alert_after and not state["error_alerted"]:
        state["error_alerted"] = True
        return True
    return False


def record_success(state):
    """A good check. Returns True if this ends an error streak that was alerted."""
    recovered = state["error_alerted"]
    state["consecutive_errors"] = 0
    state["error_alerted"] = False
    return recovered


def days_running(state, now_utc):
    start = parse_time(state["start_interval"]) + INTERVAL
    return (now_utc - start).total_seconds() / 86400


def event_message(event):
    kind, data = event
    if kind == "gap":
        return f"⚠️ ETH funding monitor: {data} funding interval(s) missing from the API"
    rate = data["funding_rate"]
    sign = "NEGATIVE - shorts PAY" if rate < 0 else "not the 0.01% default"
    return (f"⚠️ ETH funding {rate * 100:.4f}% at {data['interval_start']} ({sign}), "
            f"mark ${data['mark_price']:,.2f}")


def cushion_message(kind, value, price):
    if kind == "low":
        return (f"🚨 ETH monitor: margin cushion ${value:,.2f} (below alert level) at "
                f"ETH ${price:,.2f}. Real position would need a top-up or close.")
    return f"✅ ETH monitor: margin cushion back to ${value:,.2f} at ETH ${price:,.2f}"


def summary_message(state, price, cushion_value, now_utc, baseline):
    days = days_running(state, now_utc)
    per_year = state["total_funding"] / days * 365 if days > 0 else 0.0
    return (f"📊 ETH funding monitor (paper)\n"
            f"Running {days:.1f} days, {state['intervals']} intervals logged\n"
            f"Paper funding: ${state['total_funding']:,.2f} (~${per_year:,.0f}/yr pace)\n"
            f"Intervals off {baseline * 100:.2f}%: {state['off_baseline']} | missing: {state['gaps']}\n"
            f"ETH ${price:,.2f} | entry mark ${state['entry_mark']:,.2f}\n"
            f"Margin cushion: ${cushion_value:,.2f}")
