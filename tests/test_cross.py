import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import cross_settings as s
import cross_venues as cv
import main_cross as mc

ALIASES = s.ALIASES
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def cb_product(name, rate="0.000006", interval="3600s", time="2026-11-07T21:00:00Z",
               mid="75545", pid=None):
    return {"product_id": pid or name, "display_name": name, "mid_market_price": mid, "price": mid,
            "future_product_details": {"funding_rate": rate, "funding_interval": interval,
                                       "funding_time": time,
                                       "perpetual_details": {"funding_rate": ""}}}


def r(venue, coin, time, annual):
    return {"venue": venue, "coin": coin, "funding_time": time, "rate": 0.0,
            "interval_hours": 8.0, "annualized": annual, "price": 1.0}


class TestAnnualize(unittest.TestCase):
    def test_8h_and_1h(self):
        self.assertAlmostEqual(cv.annualize(0.0001, 8), 0.1095)       # x 3 x 365
        self.assertAlmostEqual(cv.annualize(0.000006, 1), 0.05256)    # x 24 x 365


class TestKraken(unittest.TestCase):
    def test_rows(self):
        parsed = [{"interval_start": "2026-11-07T09:00:00Z", "funding_rate": 0.0001,
                   "mark_price": 76365.0}]
        row = cv.bitnomial_rows("BTC", parsed)[0]
        self.assertEqual((row["venue"], row["coin"], row["interval_hours"]), ("kraken", "BTC", 8.0))
        self.assertAlmostEqual(row["annualized"], 0.1095)
        self.assertEqual(row["price"], 76365.0)


class TestCoinbase(unittest.TestCase):
    def test_perp_parsed(self):
        rows, skipped = cv.coinbase_rows([cb_product("BTC PERP")], ALIASES)
        self.assertEqual(skipped, [])
        row = rows[0]
        self.assertEqual((row["venue"], row["coin"]), ("coinbase", "BTC"))
        self.assertEqual(row["interval_hours"], 1.0)                   # 3600s
        self.assertEqual(row["funding_time"], "2026-11-07T21:00:00Z")
        self.assertAlmostEqual(row["annualized"], 0.05256)
        self.assertEqual(row["price"], 75545.0)

    def test_dated_future_ignored_and_no_rate_skipped(self):
        products = [cb_product("BTC 28NOV26"), cb_product("ETH PERP", rate="")]
        rows, skipped = cv.coinbase_rows(products, ALIASES)
        self.assertEqual(rows, [])
        self.assertEqual(skipped, ["ETH PERP"])

    def test_1000shib_alias_and_price(self):
        rows, _ = cv.coinbase_rows([cb_product("1000SHIB PERP", mid="0.0045")], ALIASES)
        self.assertEqual(rows[0]["coin"], "SHIB")
        self.assertAlmostEqual(rows[0]["price"], 0.0000045)            # 0.0045 / 1000

    def test_zcash_alias(self):
        rows, _ = cv.coinbase_rows([cb_product("ZCASH PERP")], ALIASES)
        self.assertEqual(rows[0]["coin"], "ZEC")


class TestKalshi(unittest.TestCase):
    MARKETS = [
        {"ticker": "KXBTCPERP", "asset_class": "Crypto", "contract_size": "0.000100",
         "underlying_multiplier": "1.000000"},
        {"ticker": "KXKSHIBPERP", "asset_class": "Crypto", "contract_size": "1000.000000",
         "underlying_multiplier": "1000.000000"},
        {"ticker": "KXAAPLPERP", "asset_class": "Equities", "contract_size": "0.020000",
         "underlying_multiplier": "1.000000"},
        {"ticker": "KXWTIFUTURE", "asset_class": "Crypto", "contract_size": "0.01"},
    ]

    def test_crypto_markets_only(self):
        m = cv.kalshi_crypto_markets(self.MARKETS, s.KALSHI_CRYPTO_CLASSES, ALIASES)
        self.assertEqual(sorted(m), ["KXBTCPERP", "KXKSHIBPERP"])     # AAPL stock + non-PERP out
        self.assertEqual(m["KXBTCPERP"], {"coin": "BTC", "contract_size": 0.0001})
        self.assertEqual(m["KXKSHIBPERP"]["coin"], "SHIB")
        self.assertEqual(m["KXKSHIBPERP"]["contract_size"], 1000000.0)  # 1000 x 1000

    def test_rows_real_values(self):
        # probe: KXBTCPERP rate 0.0002319827408406, mark 7.5599 per 0.0001 BTC contract
        m = cv.kalshi_crypto_markets(self.MARKETS, s.KALSHI_CRYPTO_CLASSES, ALIASES)
        funding = [{"market_ticker": "KXBTCPERP", "funding_time": "2026-11-07T21:00:00Z",
                    "funding_rate": 0.0002319827408406, "mark_price": "7.5599"},
                   {"market_ticker": "KXAAPLPERP", "funding_time": "2026-11-07T21:00:00Z",
                    "funding_rate": 0, "mark_price": "6.8458"}]
        rows = cv.kalshi_rows(funding, m)
        self.assertEqual(len(rows), 1)                                 # AAPL dropped
        self.assertAlmostEqual(rows[0]["price"], 75599.0)              # 7.5599 / 0.0001
        self.assertAlmostEqual(rows[0]["annualized"], 0.25402110122, places=9)  # x 1095


class TestDedupe(unittest.TestCase):
    def test_new_rows_only(self):
        seen = {}
        a = r("kraken", "BTC", "2026-11-07T09:00:00Z", 0.1)
        self.assertEqual(cv.new_rows_only([a], seen), [a])
        self.assertEqual(cv.new_rows_only([a, dict(a)], seen), [])
        b = r("kalshi", "BTC", "2026-11-07T09:00:00Z", 0.2)            # same time, other venue
        self.assertEqual(cv.new_rows_only([b], seen), [b])

    def test_prune_seen(self):
        seen = {"old": "2026-10-31T00:00:00Z", "new": "2026-11-07T00:00:00Z"}
        self.assertEqual(cv.prune_seen(seen, NOW, keep_days=7), {"new": "2026-11-07T00:00:00Z"})


class TestGaps(unittest.TestCase):
    def test_three_venue_snapshot(self):
        # the Nov 7 BTC snapshot: coinbase 5.256%, kraken 10.95%, kalshi 25.402%
        g = cv.gaps({"BTC": {"coinbase": 0.05256, "kraken": 0.1095, "kalshi": 0.25402}})
        self.assertEqual([(x["long"], x["short"]) for x in g],
                         [("coinbase", "kalshi"), ("kraken", "kalshi"), ("coinbase", "kraken")])
        self.assertAlmostEqual(g[0]["gap"], 0.20146)                   # 0.25402 - 0.05256
        self.assertAlmostEqual(g[1]["gap"], 0.14452)                   # 0.25402 - 0.1095
        self.assertAlmostEqual(g[2]["gap"], 0.05694)                   # 0.1095 - 0.05256

    def test_single_venue_coin_no_gap(self):
        self.assertEqual(cv.gaps({"XTZ": {"kraken": 0.1}}), [])

    def test_latest_picks_newest_row(self):
        # Kalshi returns NEWEST first, so the newest row must win regardless of order
        rows = [r("kalshi", "BTC", "2026-11-07T21:00:00Z", 0.10),
                r("kalshi", "BTC", "2026-11-07T13:00:00Z", 0.30),
                r("kraken", "BTC", "2026-11-07T09:00:00Z", 0.1095)]
        self.assertEqual(cv.latest_by_venue(rows, NOW), {"BTC": {"kalshi": 0.10, "kraken": 0.1095}})

    def test_min_rows(self):
        self.assertEqual(cv.min_rows(24, 1.0, 0.6), 15)      # 24 x 0.6 = 14.4 -> 15
        self.assertEqual(cv.min_rows(24, 8.0, 0.6), 2)       # 3 x 0.6 = 1.8 -> 2

    def test_coinbase_needs_15_hourly_rows(self):
        def cb_rows(n):   # n hourly rows, newest 1h before NOW, each 0.05
            times = [(NOW - timedelta(hours=1 + i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(n)]
            return [dict(r("coinbase", "BTC", t, 0.05), interval_hours=1.0) for t in times]
        self.assertEqual(cv.average_by_venue(cb_rows(14), NOW, min_coverage=0.6), {})
        avg = cv.average_by_venue(cb_rows(15), NOW, min_coverage=0.6)
        self.assertAlmostEqual(avg["BTC"]["coinbase"], 0.05)

    def test_one_8h_row_not_enough(self):
        rows = [r("kalshi", "BTC", "2026-11-07T21:00:00Z", 0.10)]
        self.assertEqual(cv.average_by_venue(rows, NOW, min_coverage=0.6), {})

    def test_thin_venue_dropped_other_kept(self):
        rows = [r("kalshi", "BTC", "2026-11-07T13:00:00Z", 0.30),
                r("kalshi", "BTC", "2026-11-07T21:00:00Z", 0.10),
                dict(r("coinbase", "BTC", "2026-11-08T11:00:00Z", 0.05), interval_hours=1.0)]
        self.assertEqual(cv.average_by_venue(rows, NOW, min_coverage=0.6), {"BTC": {"kalshi": 0.20}})

    def test_late_venue_window_ends_at_its_newest_row(self):
        # Kraken publishes late: newest row is 20h old. Rows at -20h, -28h, -36h, -44h.
        # Window = newest - 24h -> keeps -20, -28, -36 (3 rows), drops -44.
        # avg = (0.10 + 0.20 + 0.30) / 3 = 0.20. A window ending at NOW would see 1 row only.
        times = [(NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in (20, 28, 36, 44)]
        rows = [r("kraken", "BTC", t, a) for t, a in zip(times, (0.10, 0.20, 0.30, 0.90))]
        self.assertAlmostEqual(cv.average_by_venue(rows, NOW)["BTC"]["kraken"], 0.20)

    def test_stale_venue_dropped(self):
        # newest row 49h old (> 48h) -> left out of averages and latest
        times = [(NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in (49, 57)]
        rows = [r("kalshi", "BTC", t, 0.3) for t in times]
        self.assertEqual(cv.average_by_venue(rows, NOW, stale_hours=48), {})
        self.assertEqual(cv.latest_by_venue(rows, NOW, stale_hours=48), {})

    def test_exactly_48h_old_still_fresh(self):
        times = [(NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in (48, 56)]
        rows = [r("kalshi", "BTC", t, 0.3) for t in times]
        self.assertAlmostEqual(cv.latest_by_venue(rows, NOW, stale_hours=48)["BTC"]["kalshi"], 0.3)
        self.assertAlmostEqual(cv.average_by_venue(rows, NOW, stale_hours=48)["BTC"]["kalshi"], 0.3)

    def test_average_last_24h_only(self):
        rows = [r("kalshi", "BTC", "2026-11-07T13:00:00Z", 0.30),      # in (NOW - 23h)
                r("kalshi", "BTC", "2026-11-07T21:00:00Z", 0.10),      # in
                r("kalshi", "BTC", "2026-11-06T21:00:00Z", 0.90)]      # out (39h old)
        self.assertAlmostEqual(cv.average_by_venue(rows, NOW)["BTC"]["kalshi"], 0.20)


class TestGapAlerts(unittest.TestCase):
    def g(self, gap):
        return [{"coin": "BTC", "long": "coinbase", "short": "kalshi", "gap": gap,
                 "long_rate": 0.0, "short_rate": gap}]

    def test_fires_once_then_resets_below_80pct(self):
        alerted = {}
        self.assertEqual(len(cv.check_gap_alerts(self.g(0.20), 0.15, 0.8, alerted)), 1)
        self.assertEqual(cv.check_gap_alerts(self.g(0.25), 0.15, 0.8, alerted), [])   # no repeat
        self.assertEqual(cv.check_gap_alerts(self.g(0.13), 0.15, 0.8, alerted), [])   # 0.13 >= 0.12
        self.assertIn("BTC|coinbase|kalshi", alerted)
        cv.check_gap_alerts(self.g(0.11), 0.15, 0.8, alerted)                        # < 0.12 reset
        self.assertNotIn("BTC|coinbase|kalshi", alerted)
        self.assertEqual(len(cv.check_gap_alerts(self.g(0.16), 0.15, 0.8, alerted)), 1)

    def test_exactly_at_level_fires(self):
        self.assertEqual(len(cv.check_gap_alerts(self.g(0.15), 0.15, 0.8, {})), 1)

    def test_vanished_pair_resets(self):
        alerted = {"BTC|coinbase|kalshi": True}
        cv.check_gap_alerts([], 0.15, 0.8, alerted)
        self.assertEqual(alerted, {})


class TestMessagesAndErrors(unittest.TestCase):
    def test_gap_line(self):
        g = {"coin": "BTC", "long": "coinbase", "short": "kalshi", "gap": 0.20146,
             "long_rate": 0.05256, "short_rate": 0.25402}
        self.assertEqual(cv.gap_line(g),
                         "BTC: long coinbase (5.3%) / short kalshi (25.4%) = 20.1%/yr")

    def test_summary_lists_top_only(self):
        gaps = [{"coin": c, "long": "a", "short": "b", "gap": 0.1, "long_rate": 0.0,
                 "short_rate": 0.1} for c in ["A", "B", "C"]]
        text = cv.summary_message(gaps, 2, {"kraken": 51, "kalshi": 54})
        self.assertIn("A:", text)
        self.assertIn("B:", text)
        self.assertNotIn("C:", text)
        self.assertIn("kalshi 54, kraken 51", text)

    def test_summary_due(self):
        self.assertFalse(cv.summary_due(None, datetime(2026, 11, 8, 8, 59), 9))
        self.assertTrue(cv.summary_due(None, datetime(2026, 11, 8, 9, 0), 9))
        self.assertFalse(cv.summary_due("2026-11-08", datetime(2026, 11, 8, 15, 0), 9))

    def test_venue_errors_per_venue(self):
        errors = {}
        self.assertEqual([cv.record_venue_error(errors, "kalshi", 4) for _ in range(5)],
                         [False, False, False, True, False])
        self.assertFalse(cv.record_venue_error(errors, "coinbase", 4))  # separate count
        self.assertTrue(cv.record_venue_ok(errors, "kalshi"))
        self.assertFalse(cv.record_venue_ok(errors, "kalshi"))


class TestMainHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_append_then_load_recent(self):
        path = os.path.join(self.tmp, "log.csv")
        mc.append_rows([r("kraken", "BTC", "2026-11-07T09:00:00Z", 0.1095)], path)
        mc.append_rows([r("kalshi", "BTC", "2026-11-01T09:00:00Z", 0.2)], path)   # too old
        rows = mc.load_recent(path, NOW, hours=48)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["annualized"], 0.1095)
        with open(path, newline="") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 2)            # one header only

    def test_load_recent_default_keeps_72h(self):
        # late Kraken rows can be ~a day old; default must keep 60h-old rows, drop 73h-old
        path = os.path.join(self.tmp, "log.csv")
        t60 = (NOW - timedelta(hours=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t73 = (NOW - timedelta(hours=73)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mc.append_rows([r("kraken", "BTC", t60, 0.1), r("kraken", "BTC", t73, 0.2)], path)
        self.assertEqual([x["funding_time"] for x in mc.load_recent(path, NOW)], [t60])

    def test_coinbase_one_page(self):
        page = {"products": [cb_product("BTC PERP", pid="b")], "pagination": {"has_next": False}}
        with mock.patch("main_cross.get_json", return_value=page) as fake:
            rows, skipped, total = mc.fetch_coinbase()
        self.assertEqual((total, fake.call_count), (1, 1))
        self.assertEqual(fake.call_args[0][1], {"product_type": "FUTURE", "limit": 1000})

    def test_coinbase_follows_cursor(self):
        pages = [{"products": [cb_product(f"C{i} PERP", pid=str(i)) for i in range(3)],
                  "pagination": {"has_next": True, "next_cursor": "abc"}},
                 {"products": [cb_product("X PERP", pid="x")],
                  "pagination": {"has_next": False, "next_cursor": ""}}]
        with mock.patch("main_cross.get_json", side_effect=pages) as fake:
            rows, skipped, total = mc.fetch_coinbase()
        self.assertEqual(total, 4)
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(fake.call_args_list[1][0][1]["cursor"], "abc")
        self.assertNotIn("cursor", fake.call_args_list[0][0][1])

    def test_coinbase_has_next_but_no_cursor_stops(self):
        page = {"products": [cb_product("BTC PERP", pid="b")],
                "pagination": {"has_next": True, "next_cursor": ""}}
        with mock.patch("main_cross.get_json", return_value=page) as fake:
            mc.fetch_coinbase()
        self.assertEqual(fake.call_count, 1)

    def test_coinbase_stops_if_cursor_repeats_products(self):
        page = {"products": [cb_product("BTC PERP", pid="b")],
                "pagination": {"has_next": True, "next_cursor": "same"}}
        with mock.patch("main_cross.get_json", return_value=page) as fake:
            rows, skipped, total = mc.fetch_coinbase()
        self.assertEqual((total, fake.call_count), (1, 2))      # page 2 adds nothing -> stop

    def test_load_state_default(self):
        st = mc.load_state(os.path.join(self.tmp, "none.json"))
        self.assertEqual(st["seen"], {})
        self.assertIsNone(st["last_summary_date"])


if __name__ == "__main__":
    unittest.main()
