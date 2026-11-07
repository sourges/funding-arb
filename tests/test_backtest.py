import os
import shutil
import tempfile
import unittest

import backtest as bt


def row(start, end, rate, mark, index):
    return {"interval_start": start, "interval_end": end, "funding_rate": rate,
            "mark_price": mark, "price_index": index}


# One day, 3 intervals. Worked by hand:
#   qty = 1000 / 100 = 10
#   funding = 0.0001*10*101 + 0.0002*10*102 - 0.0001*10*104 = 0.101 + 0.204 - 0.104 = 0.201
#   basis   = 10 * ((105 - 100) - (104 - 101)) = 10 * (5 - 3) = 20
#   fees    = 0.0022*1000 + 0.00017*1010 + 0.0022*1050 + 0.00017*1040
#           = 2.2 + 0.1717 + 2.31 + 0.1768 = 4.8585
#   net     = 0.201 + 20 - 4.8585 = 15.3425
#   annual  = 15.3425 / 1500 * 365 / 1 = 3.73334167
#   max short loss = 10 * max(0, 1, 3) = 30
DAY = [
    row("2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 0.0001, 101.0, 100.0),
    row("2026-01-01T08:00:00Z", "2026-01-01T16:00:00Z", 0.0002, 102.0, 102.0),
    row("2026-01-01T16:00:00Z", "2026-01-02T00:00:00Z", -0.0001, 104.0, 105.0),
]


class TestStrategyA(unittest.TestCase):
    def setUp(self):
        self.r = bt.run_strategy_a(DAY)

    def test_qty(self):
        self.assertAlmostEqual(self.r["qty"], 10.0)

    def test_funding(self):
        self.assertAlmostEqual(self.r["funding"], 0.201)

    def test_basis(self):
        self.assertAlmostEqual(self.r["basis"], 20.0)

    def test_fees(self):
        self.assertAlmostEqual(self.r["fees"], 4.8585)

    def test_net(self):
        self.assertAlmostEqual(self.r["net"], 15.3425)

    def test_days_and_annualized(self):
        self.assertAlmostEqual(self.r["days"], 1.0)
        self.assertAlmostEqual(self.r["annualized"], 3.73334167, places=6)

    def test_max_short_loss(self):
        self.assertAlmostEqual(self.r["max_short_loss"], 30.0)

    def test_price_falling_means_no_short_loss(self):
        rows = [row("2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-01T08:00:00Z", "2026-01-01T16:00:00Z", 0.0001, 90.0, 90.0)]
        self.assertEqual(bt.run_strategy_a(rows)["max_short_loss"], 0.0)

    def test_flat_prices_only_funding_minus_fees(self):
        # 3 rows at 0.0001, price 100 flat: funding = 3 * 0.0001 * 10 * 100 = 0.3
        # fees = (0.0022 + 0.00017) * 1000 * 2 = 4.74 ; net = -4.44
        rows = [row("2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-01T08:00:00Z", "2026-01-01T16:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-01T16:00:00Z", "2026-01-02T00:00:00Z", 0.0001, 100.0, 100.0)]
        r = bt.run_strategy_a(rows)
        self.assertAlmostEqual(r["funding"], 0.3)
        self.assertAlmostEqual(r["basis"], 0.0)
        self.assertAlmostEqual(r["net"], -4.44)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            bt.run_strategy_a([])


class TestHalvesAndEvaluate(unittest.TestCase):
    def test_split_even_and_odd(self):
        self.assertEqual(bt.split_halves([1, 2, 3, 4]), ([1, 2], [3, 4]))
        self.assertEqual(bt.split_halves([1, 2, 3, 4, 5]), ([1, 2], [3, 4, 5]))

    def test_one_day_trade_fails_hurdle_check_logic(self):
        # DAY annualizes to 373% -> beats hurdle; halves: [r1] and [r2, r3]
        # half1: one row, entry=exit -> basis 0, funding 0.101,
        #        fees = 0.0022*1000 + 0.00017*1010 twice = 4.7434 -> net < 0 -> FAIL
        result = bt.evaluate(DAY)
        self.assertTrue(result["beats_hurdle"])
        self.assertFalse(result["both_halves"])
        self.assertFalse(result["passed"])
        self.assertAlmostEqual(result["half1"]["net"], 0.101 - 4.7434)

    def test_pass_when_both_conditions_hold(self):
        # 2 rows per half, each half gains basis 10*(10-0)=100 >> fees
        rows = [row("2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-01T08:00:00Z", "2026-01-01T16:00:00Z", 0.0001, 100.0, 110.0),
                row("2026-01-01T16:00:00Z", "2026-01-02T00:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-02T00:00:00Z", "2026-01-02T08:00:00Z", 0.0001, 100.0, 110.0)]
        result = bt.evaluate(rows)
        self.assertTrue(result["both_halves"])
        self.assertTrue(result["passed"])

    def test_hurdle_is_strictly_greater(self):
        result = bt.evaluate(DAY, hurdle=bt.run_strategy_a(DAY)["annualized"])
        self.assertFalse(result["beats_hurdle"])


class TestStatsAndCompare(unittest.TestCase):
    def test_funding_stats(self):
        s = bt.funding_stats(DAY)
        # avg = (0.0001 + 0.0002 - 0.0001) / 3 = 0.0000666667 ; x 1095 = 0.073
        self.assertEqual(s["intervals"], 3)
        self.assertAlmostEqual(s["average"], 0.0002 / 3)
        self.assertAlmostEqual(s["annualized"], 0.073)
        self.assertAlmostEqual(s["pct_negative"], 1 / 3)
        self.assertAlmostEqual(s["pct_baseline"], 1 / 3)

    def test_zero_rate_is_not_negative(self):
        rows = [row("A", "", 0.0, 1, 1), row("B", "", -0.0001, 1, 1), row("C", "", 0.0001, 1, 1)]
        s = bt.funding_stats(rows)
        self.assertAlmostEqual(s["pct_negative"], 1 / 3)   # only B
        self.assertAlmostEqual(s["average"], 0.0)

    def test_compare_rates_only_overlap(self):
        a = [row("A", "", 0.0001, 1, 1), row("B", "", 0.0002, 1, 1), row("C", "", 0.0001, 1, 1)]
        b = [row("B", "", 0.0002, 1, 1), row("C", "", 0.0003, 1, 1), row("D", "", 0.0001, 1, 1)]
        self.assertEqual(bt.compare_rates(a, b), {"overlap": 2, "matches": 1})


class TestLoadRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_reads_floats(self):
        path = os.path.join(self.tmp, "f.csv")
        with open(path, "w", newline="") as f:
            f.write("interval_start,interval_end,funding_rate,mark_price,price_index,product_id\n")
            f.write("2026-05-17T16:00:00Z,2026-05-18T00:00:00Z,0.0001,85000.0,84990.0,5614\n")
        rows = bt.load_rows(path)
        self.assertEqual(rows[0]["funding_rate"], 0.0001)
        self.assertEqual(rows[0]["mark_price"], 85000.0)
        self.assertEqual(rows[0]["price_index"], 84990.0)

    def test_blank_price_becomes_none(self):
        path = os.path.join(self.tmp, "f.csv")
        with open(path, "w", newline="") as f:
            f.write("interval_start,interval_end,funding_rate,mark_price,price_index,product_id\n")
            f.write("2026-07-05T00:00:00Z,2026-07-05T08:00:00Z,0.0001,61000.0,,5614\n")
        self.assertIsNone(bt.load_rows(path)[0]["price_index"])


class TestMissingPrices(unittest.TestCase):
    def test_blank_index_in_middle_is_fine(self):
        # same as DAY but middle index blank -> identical result (index only used at ends)
        rows = [dict(r) for r in DAY]
        rows[1]["price_index"] = None
        self.assertAlmostEqual(bt.run_strategy_a(rows)["net"], 15.3425)

    def test_blank_index_at_exit_raises(self):
        rows = [dict(r) for r in DAY]
        rows[2]["price_index"] = None
        with self.assertRaises(ValueError):
            bt.run_strategy_a(rows)

    def test_blank_index_at_entry_raises(self):
        rows = [dict(r) for r in DAY]
        rows[0]["price_index"] = None
        with self.assertRaises(ValueError):
            bt.run_strategy_a(rows)

    def test_blank_mark_in_middle_raises(self):
        rows = [dict(r) for r in DAY]
        rows[1]["mark_price"] = None
        with self.assertRaises(ValueError):
            bt.run_strategy_a(rows)


if __name__ == "__main__":
    unittest.main()
