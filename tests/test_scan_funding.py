import os
import shutil
import tempfile
import unittest

import fetch_funding as ff
import scan_funding as sf


def row(start, rate):
    return {"interval_start": start, "interval_end": "", "funding_rate": rate,
            "mark_price": 100.0, "price_index": 100.0}


class TestSummarize(unittest.TestCase):
    def test_values(self):
        rows = [row("2026-06-01T01:00:00Z", 0.0001), row("2026-06-01T09:00:00Z", 0.0005),
                row("2026-06-01T17:00:00Z", -0.0002), row("2026-06-02T01:00:00Z", 0.0001)]
        s = sf.summarize("SOL", rows)
        # avg = (0.0001 + 0.0005 - 0.0002 + 0.0001) / 4 = 0.000125 ; x 1095 = 0.136875
        self.assertEqual(s["coin"], "SOL")
        self.assertEqual(s["first"], "2026-06-01")
        self.assertEqual(s["intervals"], 4)
        self.assertAlmostEqual(s["annualized"], 0.136875)
        self.assertAlmostEqual(s["pct_baseline"], 0.5)     # 2 of 4 at 0.0001
        self.assertAlmostEqual(s["pct_negative"], 0.25)    # 1 of 4
        self.assertEqual(s["max_rate"], 0.0005)
        self.assertEqual(s["min_rate"], -0.0002)

    def test_coin_from_filename(self):
        self.assertEqual(sf.coin_from_filename(os.path.join("data", "scan", "funding_AAVE.csv")), "AAVE")


class TestScanFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_sorted_highest_first_and_ignores_other_files(self):
        ff.write_csv([dict(row("a", 0.0001), interval_end="", product_id=1)],
                     os.path.join(self.tmp, "funding_LOW.csv"))
        ff.write_csv([dict(row("a", 0.0003), interval_end="", product_id=1)],
                     os.path.join(self.tmp, "funding_HIGH.csv"))
        # a valid funding CSV that isn't named funding_*.csv must be ignored
        ff.write_csv([dict(row("a", 0.0009), interval_end="", product_id=1)],
                     os.path.join(self.tmp, "backup.csv"))
        results = sf.scan(self.tmp)
        self.assertEqual([r["coin"] for r in results], ["HIGH", "LOW"])

    def test_empty_folder(self):
        self.assertEqual(sf.scan(self.tmp), [])


class TestScanFlag(unittest.TestCase):
    def test_scan_flag_uses_scan_coins_and_folder(self):
        calls = []
        original = ff.fetch_all
        ff.fetch_all = lambda coins, begin, folder, get=None: calls.append((coins, folder))
        try:
            ff.main(["--scan"])
        finally:
            ff.fetch_all = original
        self.assertEqual(calls[0][1], "data/scan")
        self.assertEqual(len(calls[0][0]), 17)
        self.assertEqual(calls[0][0]["SOL"], "SOLUS")


if __name__ == "__main__":
    unittest.main()
