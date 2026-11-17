"""agent_summary.py: every expected number below is worked out by hand in the comments."""
import csv
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import agent_summary as a
import cross_venues as cv

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 12)


def r(venue, coin, time, annual, rate=0.0, interval=8.0, price=1.0):
    return {"venue": venue, "coin": coin, "funding_time": time, "rate": rate,
            "interval_hours": interval, "annualized": annual, "price": price}


def d(day):
    return date(2026, 11, day)


class TestDailyAverages(unittest.TestCase):
    def test_average_of_a_full_day(self):
        rows = [r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.10),
                r("kraken", "BTC", "2026-11-10T08:00:00Z", 0.20),
                r("kraken", "BTC", "2026-11-10T16:00:00Z", 0.30)]
        # (0.10 + 0.20 + 0.30) / 3 = 0.20
        self.assertAlmostEqual(a.daily_averages(rows, TODAY)["BTC"]["kraken"][d(10)], 0.20)

    def test_day_with_too_few_rows_is_left_out(self):
        # 8h venue needs ceil(3 x 0.6) = 2 rows. One row is not a day.
        rows = [r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.10)]
        self.assertEqual(a.daily_averages(rows, TODAY), {})
        rows.append(r("kraken", "BTC", "2026-11-10T08:00:00Z", 0.30))
        self.assertAlmostEqual(a.daily_averages(rows, TODAY)["BTC"]["kraken"][d(10)], 0.20)

    def test_hourly_venue_needs_15_rows(self):
        # hourly venue needs ceil(24 x 0.6) = 15 rows
        rows = [r("coinbase", "BTC", f"2026-11-10T{h:02d}:00:00Z", 0.04, interval=1.0)
                for h in range(14)]
        self.assertEqual(a.daily_averages(rows, TODAY), {})
        rows.append(r("coinbase", "BTC", "2026-11-10T14:00:00Z", 0.19, interval=1.0))
        # 14 x 0.04 + 0.19 = 0.75, / 15 = 0.05
        self.assertAlmostEqual(a.daily_averages(rows, TODAY)["BTC"]["coinbase"][d(10)], 0.05)

    def test_today_is_left_out(self):
        rows = [r("kraken", "BTC", "2026-11-12T00:00:00Z", 0.10),
                r("kraken", "BTC", "2026-11-12T08:00:00Z", 0.20)]
        self.assertEqual(a.daily_averages(rows, TODAY), {})

    def test_days_and_coins_are_kept_apart(self):
        rows = [r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.10),
                r("kraken", "BTC", "2026-11-10T08:00:00Z", 0.10),
                r("kraken", "BTC", "2026-11-11T00:00:00Z", 0.40),
                r("kraken", "BTC", "2026-11-11T08:00:00Z", 0.40),
                r("kraken", "ETH", "2026-11-10T00:00:00Z", 0.70),
                r("kraken", "ETH", "2026-11-10T08:00:00Z", 0.70)]
        got = a.daily_averages(rows, TODAY)
        self.assertAlmostEqual(got["BTC"]["kraken"][d(10)], 0.10)
        self.assertAlmostEqual(got["BTC"]["kraken"][d(11)], 0.40)
        self.assertAlmostEqual(got["ETH"]["kraken"][d(10)], 0.70)


class TestPairDailyGaps(unittest.TestCase):
    def test_gap_is_second_venue_minus_first(self):
        daily = {"BTC": {"kraken": {d(10): 0.20}, "coinbase": {d(10): 0.05}}}
        # alphabet: coinbase, kraken -> kraken minus coinbase = 0.20 - 0.05 = 0.15
        got = a.pair_daily_gaps(daily)
        self.assertEqual(list(got), [("BTC", "coinbase", "kraken")])
        self.assertAlmostEqual(got[("BTC", "coinbase", "kraken")][d(10)], 0.15)

    def test_only_days_both_venues_have(self):
        daily = {"BTC": {"kraken": {d(10): 0.20, d(11): 0.30}, "coinbase": {d(11): 0.40}}}
        got = a.pair_daily_gaps(daily)[("BTC", "coinbase", "kraken")]
        self.assertEqual(list(got), [d(11)])
        self.assertAlmostEqual(got[d(11)], -0.10)          # 0.30 - 0.40

    def test_no_shared_day_no_pair_and_three_venues_make_three_pairs(self):
        self.assertEqual(a.pair_daily_gaps(
            {"BTC": {"kraken": {d(10): 0.2}, "coinbase": {d(11): 0.4}}}), {})
        three = {"BTC": {"kraken": {d(10): 0.2}, "coinbase": {d(10): 0.4}, "kalshi": {d(10): 0.1}}}
        self.assertEqual(sorted(a.pair_daily_gaps(three)),
                         [("BTC", "coinbase", "kalshi"), ("BTC", "coinbase", "kraken"),
                          ("BTC", "kalshi", "kraken")])


class TestStreaks(unittest.TestCase):
    KEY = ("BTC", "coinbase", "kraken")

    def test_counts_back_from_the_last_day_until_under_the_level(self):
        gaps = {self.KEY: {d(8): 0.12, d(9): 0.05, d(10): 0.11, d(11): 0.15}}
        # Nov 11 yes, Nov 10 yes, Nov 9 is 0.05 (under 0.10) -> 2 days. Nov 8 doesn't count.
        got = a.streaks(gaps, 0.10, d(11))
        self.assertEqual(got, [{"coin": "BTC", "long": "coinbase", "short": "kraken",
                                "days": 2, "latest_gap": 0.15}])

    def test_negative_gap_points_the_pair_the_other_way(self):
        gaps = {self.KEY: {d(10): -0.20, d(11): -0.30}}
        got = a.streaks(gaps, 0.10, d(11))[0]
        self.assertEqual((got["long"], got["short"], got["days"]), ("kraken", "coinbase", 2))
        self.assertAlmostEqual(got["latest_gap"], 0.30)

    def test_a_sign_change_ends_the_streak(self):
        gaps = {self.KEY: {d(10): -0.50, d(11): 0.50}}
        self.assertEqual(a.streaks(gaps, 0.10, d(11))[0]["days"], 1)

    def test_exactly_at_the_level_counts(self):
        gaps = {self.KEY: {d(10): 0.10, d(11): 0.10}}
        self.assertEqual(a.streaks(gaps, 0.10, d(11))[0]["days"], 2)

    def test_a_missing_day_ends_the_streak(self):
        gaps = {self.KEY: {d(8): 0.30, d(10): 0.30, d(11): 0.30}}      # no Nov 9
        self.assertEqual(a.streaks(gaps, 0.10, d(11))[0]["days"], 2)

    def test_not_listed_when_the_last_day_is_under_the_level_or_missing(self):
        self.assertEqual(a.streaks({self.KEY: {d(10): 0.30, d(11): 0.09}}, 0.10, d(11)), [])
        self.assertEqual(a.streaks({self.KEY: {d(9): 0.30, d(10): 0.30}}, 0.10, d(11)), [])

    def test_longest_first(self):
        gaps = {("AAA", "coinbase", "kraken"): {d(11): 0.90},
                ("BBB", "coinbase", "kraken"): {d(9): 0.2, d(10): 0.2, d(11): 0.2}}
        self.assertEqual([x["coin"] for x in a.streaks(gaps, 0.10, d(11))], ["BBB", "AAA"])


class TestFlips(unittest.TestCase):
    KEY = ("BTC", "coinbase", "kraken")

    def test_counts_sign_changes(self):
        gaps = {self.KEY: {d(8): 0.1, d(9): -0.1, d(10): -0.2, d(11): 0.3}}
        # + to - (1), - to - (0), - to + (2) -> 2 flips in 4 days
        self.assertEqual(a.flips(gaps, d(5), d(11)),
                         [{"coin": "BTC", "a": "coinbase", "b": "kraken", "flips": 2, "days": 4}])

    def test_no_flip_no_line(self):
        self.assertEqual(a.flips({self.KEY: {d(10): 0.1, d(11): 0.4}}, d(5), d(11)), [])

    def test_zero_days_are_skipped(self):
        # + , 0 , +  is not a flip;  + , 0 , -  is one flip in 2 counted days
        self.assertEqual(a.flips({self.KEY: {d(9): 0.1, d(10): 0.0, d(11): 0.1}}, d(5), d(11)), [])
        got = a.flips({self.KEY: {d(9): 0.1, d(10): 0.0, d(11): -0.1}}, d(5), d(11))[0]
        self.assertEqual((got["flips"], got["days"]), (1, 2))

    def test_days_outside_the_window_are_ignored(self):
        gaps = {self.KEY: {d(3): -0.1, d(10): 0.1, d(11): 0.2, d(12): -0.3}}
        self.assertEqual(a.flips(gaps, d(5), d(11)), [])
        # both edge days are inside the window
        self.assertEqual(a.flips(gaps, d(3), d(11))[0]["flips"], 1)
        self.assertEqual(a.flips(gaps, d(5), d(12))[0]["flips"], 1)

    def test_most_flips_first(self):
        gaps = {("AAA", "coinbase", "kraken"): {d(10): 0.1, d(11): -0.1},
                ("BBB", "coinbase", "kraken"): {d(9): 0.1, d(10): -0.1, d(11): 0.1}}
        self.assertEqual([x["coin"] for x in a.flips(gaps, d(5), d(11))], ["BBB", "AAA"])


class TestMovers(unittest.TestCase):
    def rows(self):
        times_old = ["2026-11-10T16:00:00Z", "2026-11-11T00:00:00Z", "2026-11-11T08:00:00Z"]
        times_new = ["2026-11-11T16:00:00Z", "2026-11-12T00:00:00Z", "2026-11-12T08:00:00Z"]
        rows = [r("kraken", "BTC", t, 0.05) for t in times_old]
        rows += [r("kalshi", "BTC", t, 0.10) for t in times_old]
        rows += [r("kraken", "BTC", t, 0.30) for t in times_new]
        rows += [r("kalshi", "BTC", t, 0.10) for t in times_new]
        return rows

    def test_change_is_now_minus_one_day_earlier(self):
        # now: kraken 0.30, kalshi 0.10 -> long kalshi / short kraken, gap 0.20
        # a day earlier, same direction: kraken 0.05 - kalshi 0.10 = -0.05
        # change = 0.20 - (-0.05) = 0.25
        got = a.movers(self.rows(), NOW)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["coin"], got[0]["long"], got[0]["short"]),
                         ("BTC", "kalshi", "kraken"))
        self.assertAlmostEqual(got[0]["now"], 0.20)
        self.assertAlmostEqual(got[0]["before"], -0.05)
        self.assertAlmostEqual(got[0]["change"], 0.25)

    def test_pair_with_no_earlier_day_is_left_out(self):
        rows = [x for x in self.rows() if x["funding_time"] > "2026-11-11T08:00:00Z"]
        self.assertEqual(a.movers(rows, NOW), [])

    def test_biggest_change_first_either_direction(self):
        rows = self.rows()
        for coin, old_kraken, new_kraken in (("ETH", 0.10, 0.12), ("SOL", 0.10, -0.60),
                                             ("ADA", 0.60, 0.20)):
            for t in ["2026-11-10T16:00:00Z", "2026-11-11T00:00:00Z", "2026-11-11T08:00:00Z"]:
                rows += [r("kraken", coin, t, old_kraken), r("kalshi", coin, t, 0.10)]
            for t in ["2026-11-11T16:00:00Z", "2026-11-12T00:00:00Z", "2026-11-12T08:00:00Z"]:
                rows += [r("kraken", coin, t, new_kraken), r("kalshi", coin, t, 0.10)]
        # ETH: 0 -> 0.02, change +0.02
        # SOL: 0 -> 0.70 (kalshi 0.10 - kraken -0.60), change +0.70
        # ADA: 0.50 -> 0.10 (the gap shrank), change -0.40: a big drop ranks above BTC's +0.25
        got = a.movers(rows, NOW)
        self.assertEqual([x["coin"] for x in got], ["SOL", "ADA", "BTC", "ETH"])
        self.assertAlmostEqual(got[1]["change"], -0.40)


class TestVenueHabits(unittest.TestCase):
    def test_average_and_share_at_the_usual_rate(self):
        rows = [r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.10, rate=0.0001),
                r("kraken", "BTC", "2026-11-10T08:00:00Z", 0.10, rate=0.0001),
                r("kraken", "ETH", "2026-11-10T08:00:00Z", 0.10, rate=0.0001),
                r("kraken", "ETH", "2026-11-10T16:00:00Z", 0.30, rate=0.0003),
                r("kraken", "ETH", "2026-11-01T16:00:00Z", 9.99, rate=0.0003)]   # older than 7 days
        got = a.venue_habits(rows, NOW, days=7)["kraken"]
        # 4 rows in the window: (0.10 x 3 + 0.30) / 4 = 0.15 ; 3 of 4 at 0.0001 = 0.75
        self.assertEqual((got["rows"], got["coins"], got["usual_rate"]), (4, 2, 0.0001))
        self.assertAlmostEqual(got["average"], 0.15)
        self.assertAlmostEqual(got["usual_share"], 0.75)

    def test_venues_are_kept_apart(self):
        rows = [r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.10),
                r("kalshi", "BTC", "2026-11-10T00:00:00Z", 0.50)]
        got = a.venue_habits(rows, NOW)
        self.assertAlmostEqual(got["kraken"]["average"], 0.10)
        self.assertAlmostEqual(got["kalshi"]["average"], 0.50)


class TestPriceChanges(unittest.TestCase):
    VENUES = ["kraken", "coinbase", "kalshi"]

    def test_24h_and_7d_change(self):
        rows = [r("kraken", "BTC", "2026-11-05T08:00:00Z", 0, price=100.0),
                r("kraken", "BTC", "2026-11-11T08:00:00Z", 0, price=110.0),
                r("kraken", "BTC", "2026-11-12T08:00:00Z", 0, price=121.0)]
        got = a.price_changes(rows, self.VENUES)["BTC"]
        # 121 / 110 - 1 = 0.10 ; 121 / 100 - 1 = 0.21
        self.assertEqual((got["venue"], got["price"]), ("kraken", 121.0))
        self.assertAlmostEqual(got["change_24h"], 0.10)
        self.assertAlmostEqual(got["change_7d"], 0.21)

    def test_none_when_there_is_no_row_old_enough(self):
        rows = [r("kraken", "BTC", "2026-11-11T08:00:00Z", 0, price=110.0),
                r("kraken", "BTC", "2026-11-12T08:00:00Z", 0, price=121.0)]
        got = a.price_changes(rows, self.VENUES)["BTC"]
        self.assertAlmostEqual(got["change_24h"], 0.10)
        self.assertIsNone(got["change_7d"])

    def test_none_when_the_nearest_old_row_is_too_far_from_the_target(self):
        # target is Nov 11 08:00; the only older row is 10 hours before it (slack is 9)
        rows = [r("kraken", "BTC", "2026-11-10T22:00:00Z", 0, price=110.0),
                r("kraken", "BTC", "2026-11-12T08:00:00Z", 0, price=121.0)]
        self.assertIsNone(a.price_changes(rows, self.VENUES)["BTC"]["change_24h"])
        rows[0]["funding_time"] = "2026-11-10T23:00:00Z"                 # 9 hours: allowed
        self.assertAlmostEqual(a.price_changes(rows, self.VENUES)["BTC"]["change_24h"], 0.10)

    def test_a_row_after_the_target_is_not_used(self):
        rows = [r("kraken", "BTC", "2026-11-11T08:00:00Z", 0, price=110.0),
                r("kraken", "BTC", "2026-11-11T16:00:00Z", 0, price=999.0),
                r("kraken", "BTC", "2026-11-12T08:00:00Z", 0, price=121.0)]
        self.assertAlmostEqual(a.price_changes(rows, self.VENUES)["BTC"]["change_24h"], 0.10)

    def test_first_venue_in_the_list_that_has_the_coin(self):
        rows = [r("coinbase", "ZEC", "2026-11-11T08:00:00Z", 0, price=50.0),
                r("coinbase", "ZEC", "2026-11-12T08:00:00Z", 0, price=40.0),
                r("kalshi", "ZEC", "2026-11-12T08:00:00Z", 0, price=77.0)]
        got = a.price_changes(rows, self.VENUES)["ZEC"]
        self.assertEqual(got["venue"], "coinbase")
        self.assertAlmostEqual(got["change_24h"], -0.20)                 # 40 / 50 - 1

    def test_rows_without_a_price_are_ignored(self):
        rows = [r("kraken", "BTC", "2026-11-12T08:00:00Z", 0, price=None)]
        self.assertEqual(a.price_changes(rows, self.VENUES), {})


class TestDataHealth(unittest.TestCase):
    def test_counts_and_missing_coins(self):
        rows = [r("kraken", "BTC", "2026-11-08T00:00:00Z", 0),
                r("kraken", "BTC", "2026-11-12T08:00:00Z", 0),
                r("kraken", "ETH", "2026-11-10T08:00:00Z", 0),      # in the week, not in 24h
                r("kraken", "XRP", "2026-11-01T08:00:00Z", 0),      # older than the week
                r("kalshi", "BTC", "2026-11-12T00:00:00Z", 0)]
        got = a.data_health(rows, NOW, days=7)
        k = got["kraken"]
        self.assertEqual((k["rows"], k["rows_24h"], k["missing"]), (4, 1, ["ETH"]))
        self.assertEqual(k["first"], datetime(2026, 11, 1, 8, tzinfo=timezone.utc))
        self.assertEqual(k["last"], datetime(2026, 11, 12, 8, tzinfo=timezone.utc))
        self.assertEqual((got["kalshi"]["rows"], got["kalshi"]["rows_24h"],
                          got["kalshi"]["missing"]), (1, 1, []))


class TestDropCoins(unittest.TestCase):
    def test_excluded_coins_are_removed_and_listed_once(self):
        rows = [r("coinbase", "US 500", "2026-11-10T00:00:00Z", 0.5),
                r("coinbase", "US 500", "2026-11-10T01:00:00Z", 0.5),
                r("coinbase", "BTC", "2026-11-10T00:00:00Z", 0.1),
                r("coinbase", "CHINA", "2026-11-10T00:00:00Z", 0.9)]
        kept, dropped = a.drop_coins(rows, ["US 500", "CHINA", "TECH"])
        self.assertEqual([x["coin"] for x in kept], ["BTC"])
        self.assertEqual(dropped, ["CHINA", "US 500"])           # TECH wasn't in the rows

    def test_nothing_to_drop(self):
        rows = [r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.1)]
        self.assertEqual(a.drop_coins(rows, ["TECH"]), (rows, []))


class TestFileAndText(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "cross_funding.csv")
        self.out = os.path.join(self.dir, "agent_summary.txt")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write_log(self, rows):
        with open(self.log, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cv.LOG_FIELDS)
            w.writeheader()
            w.writerows(rows)

    def sample(self):
        rows = []
        for day in (10, 11):
            for hour in (0, 8, 16):
                t = f"2026-11-{day}T{hour:02d}:00:00Z"
                rows.append(r("kraken", "BTC", t, 0.30, rate=0.0001, price=100.0))
                rows.append(r("kalshi", "BTC", t, 0.10, rate=0.0002, price=100.0))
        for hour in (0, 8):
            t = f"2026-11-12T{hour:02d}:00:00Z"
            rows.append(r("kraken", "BTC", t, 0.30, rate=0.0001, price=105.0))
            rows.append(r("kalshi", "BTC", t, 0.10, rate=0.0002, price=105.0))
        return rows

    def test_load_rows_reads_numbers_and_blank_price(self):
        self.write_log([r("kraken", "BTC", "2026-11-10T00:00:00Z", 0.1095, rate=0.0001, price=76365.0),
                        r("coinbase", "XYZ", "2026-11-10T00:00:00Z", 0.05, interval=1.0, price=None)])
        got = a.load_rows(self.log)
        self.assertEqual(got[0], {"venue": "kraken", "coin": "BTC",
                                  "funding_time": "2026-11-10T00:00:00Z", "rate": 0.0001,
                                  "interval_hours": 8.0, "annualized": 0.1095, "price": 76365.0})
        self.assertIsNone(got[1]["price"])
        self.assertEqual(got[1]["interval_hours"], 1.0)

    def test_missing_file_is_an_empty_list_and_says_no_data(self):
        self.assertEqual(a.load_rows(os.path.join(self.dir, "nope.csv")), [])
        self.assertIn("NO DATA", a.build_text([], NOW))

    def test_text_has_the_hand_worked_lines(self):
        text = a.build_text(self.sample(), NOW)
        # 24h gap: kraken 30% - kalshi 10% = 20%
        self.assertIn("BTC: long kalshi (10.0%) / short kraken (30.0%) = 20.0%/yr", text)
        # Nov 10 and Nov 11 are both full days at 20% -> 2-day streak
        self.assertIn("BTC: long kalshi / short kraken: 2 days, latest day 20.0%", text)
        # same gap a day earlier -> change 0
        self.assertIn("+20.0% -> +20.0% (change +0.0%)", text)
        # kraken: all 8 rows at 0.0001 -> 100% at 0.0100% per interval, average +30.0%
        self.assertIn("kraken: average +30.0%/yr over 8 rows, 1 coins; 100% of rows at its "
                      "usual rate of 0.0100% per interval", text)
        # price 105 / 100 - 1 = +5.0% over 24h, no 7d row
        self.assertIn("BTC: +5.0% / n/a (kraken)", text)
        # data starts Nov 10 00:00, now Nov 12 12:00 -> 2.5 days
        self.assertIn("Data starts 2026-11-10 00:00 UTC: 2.5 days", text)
        self.assertIn("kraken: 8 rows since 2026-11-10, 3 in the last 24h, newest row 4.0h old", text)
        self.assertIn("4. FLIPS: daily gap changed sign, 2026-11-05 to 2026-11-11\nnone", text)

    def test_excluded_coins_never_reach_the_text(self):
        rows = self.sample()
        for t in ("2026-11-11T16:00:00Z", "2026-11-12T00:00:00Z", "2026-11-12T08:00:00Z"):
            rows.append(r("kraken", "TECH", t, 0.90, price=50.0))
            rows.append(r("kalshi", "TECH", t, -0.90, price=50.0))
        with mock.patch.object(a.s, "EXCLUDE_COINS", ["TECH"]):
            text = a.build_text(rows, NOW)
        self.assertIn("Left out (not crypto): TECH", text)
        self.assertEqual(text.count("TECH"), 1)                 # only on that one line
        # the 180% TECH gap would have been the top line; BTC's 20% is still first
        self.assertIn("1. TOP GAPS, 24h average\nBTC: long kalshi", text)

    def test_no_left_out_line_when_nothing_was_dropped(self):
        with mock.patch.object(a.s, "EXCLUDE_COINS", ["TECH"]):
            self.assertNotIn("Left out", a.build_text(self.sample(), NOW))

    def test_text_never_mentions_profit(self):
        text = a.build_text(self.sample(), NOW).lower()
        for word in ("p&l", "profit", "rules_3", "return"):
            self.assertNotIn(word, text)

    def test_main_writes_the_summary_and_leaves_the_log_untouched(self):
        self.write_log(self.sample())
        with open(self.log, "rb") as f:
            before = f.read()
        with mock.patch.object(a.cs, "LOG_FILE", self.log), \
                mock.patch.object(a.s, "SUMMARY_FILE", self.out), \
                mock.patch("builtins.print"):
            a.main()
        with open(self.log, "rb") as f:
            self.assertEqual(f.read(), before)
        with open(self.out, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("FUNDING SUMMARY "))
        self.assertEqual(sorted(os.listdir(self.dir)), ["agent_summary.txt", "cross_funding.csv"])


if __name__ == "__main__":
    unittest.main()
