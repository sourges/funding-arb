import unittest

import backtest as bt
import backtest_2 as bt2
from tests.test_backtest import DAY, row

# DAY: qty = 10, entry_mark = 101, marks 101, 102, 104. Maintenance rate 0.16.
#   maintenance per row = 0.16 * 10 * mark = 161.6, 163.2, 166.4
#   short loss per row  = 10 * (mark - 101) = 0, 10, 30
QTY, ENTRY_MARK, RATE = 10.0, 101.0, 0.16


class TestLiquidationCheck(unittest.TestCase):
    def test_safe_margin(self):
        # margin 200: cushions 200-161.6=38.4 | 190-163.2=26.8 | 170-166.4=3.6
        r = bt2.liquidation_check(DAY, QTY, ENTRY_MARK, 200.0, RATE)
        self.assertFalse(r["liquidated"])
        self.assertIsNone(r["first_liquidation"])
        self.assertAlmostEqual(r["min_cushion"], 3.6)

    def test_liquidated_on_last_row(self):
        # margin 190: cushions 28.4 | 16.8 | 160-166.4 = -6.4 -> liquidated at row 3
        r = bt2.liquidation_check(DAY, QTY, ENTRY_MARK, 190.0, RATE)
        self.assertTrue(r["liquidated"])
        self.assertEqual(r["first_liquidation"], "2026-01-01T16:00:00Z")
        self.assertAlmostEqual(r["min_cushion"], -6.4)

    def test_first_liquidation_is_earliest(self):
        # margin 165: cushions 3.4 | 155-163.2=-8.2 | 135-166.4=-31.4 -> first is row 2
        r = bt2.liquidation_check(DAY, QTY, ENTRY_MARK, 165.0, RATE)
        self.assertEqual(r["first_liquidation"], "2026-01-01T08:00:00Z")
        self.assertAlmostEqual(r["min_cushion"], -31.4)

    def test_exactly_at_maintenance_is_not_liquidated(self):
        # margin 196.4: row 3 cushion = 166.4 - 166.4 = 0 -> not liquidated (strict <)
        r = bt2.liquidation_check(DAY, QTY, ENTRY_MARK, 196.4, RATE)
        self.assertFalse(r["liquidated"])

    def test_price_falling_is_safe(self):
        # short gains when price falls: margin 100, mark 100 -> 50
        rows = [row("a", "", 0.0001, 100.0, 100.0), row("b", "", 0.0001, 50.0, 50.0)]
        # cushions: 100 - 0.16*10*100 = -60 (too little margin at entry!) | 100+500-80 = 520
        r = bt2.liquidation_check(rows, 10.0, 100.0, 100.0, RATE)
        self.assertEqual(r["first_liquidation"], "a")
        rows_ok = [row("a", "", 0.0001, 100.0, 100.0), row("b", "", 0.0001, 50.0, 50.0)]
        r2 = bt2.liquidation_check(rows_ok, 10.0, 100.0, 200.0, RATE)
        self.assertFalse(r2["liquidated"])            # 200-160=40 | 700-80=620
        self.assertAlmostEqual(r2["min_cushion"], 40.0)


class TestEvaluate2(unittest.TestCase):
    def test_capital_used_for_annualized(self):
        # DAY net 15.3425 on $1,740 over 1 day: 15.3425 / 1740 = 0.00881753 ; x 365 = 3.2183980
        result = bt2.evaluate_2(DAY, RATE)
        self.assertAlmostEqual(result["full"]["annualized"], 3.2183980, places=6)

    def test_backtest_1_default_unchanged(self):
        # backtest.evaluate without capital still uses $1,500
        self.assertAlmostEqual(bt.evaluate(DAY)["full"]["annualized"], 3.73334167, places=6)

    def test_liquidation_fails_even_if_profitable(self):
        # 4 rows, both halves profitable (basis +100 each), but margin 50 is below
        # maintenance 0.16*10*100 = 160 at entry -> liquidated -> FAIL
        rows = [row("2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-01T08:00:00Z", "2026-01-01T16:00:00Z", 0.0001, 100.0, 110.0),
                row("2026-01-01T16:00:00Z", "2026-01-02T00:00:00Z", 0.0001, 100.0, 100.0),
                row("2026-01-02T00:00:00Z", "2026-01-02T08:00:00Z", 0.0001, 100.0, 110.0)]
        bad = bt2.evaluate_2(rows, RATE, margin=50.0)
        self.assertTrue(bad["beats_hurdle"])
        self.assertTrue(bad["both_halves"])
        self.assertTrue(bad["liquidation"]["liquidated"])
        self.assertFalse(bad["passed"])
        good = bt2.evaluate_2(rows, RATE)               # default $740 margin
        self.assertFalse(good["liquidation"]["liquidated"])
        self.assertTrue(good["passed"])

    def test_locked_settings(self):
        self.assertEqual(bt2.MARGIN, 740.0)
        self.assertEqual(bt2.CAPITAL, 1740.0)
        self.assertEqual(bt2.MAINT_RATE, {"BTC": 0.161, "ETH": 0.157})


if __name__ == "__main__":
    unittest.main()
