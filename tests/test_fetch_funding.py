import csv
import os
import shutil
import tempfile
import unittest

import fetch_funding as ff


class FakeApi:
    """Stands in for http_get: returns queued pages and records every call."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, params))
        if not self.pages:
            raise AssertionError("FakeApi called more times than pages queued")
        return self.pages.pop(0)


def raw(start, rate, mark="100.0"):
    return {"interval_start": start, "interval_end": start + "-end",
            "funding_rate": rate, "mark_price": mark,
            "price_index": "99.5", "product_id": 7}


class TestParseRow(unittest.TestCase):
    def test_strings_become_floats(self):
        row = ff.parse_row(raw("2026-06-01T00:00:00Z", "0.000125", "101250.00"))
        self.assertEqual(row["funding_rate"], 0.000125)
        self.assertEqual(row["mark_price"], 101250.0)
        self.assertEqual(row["price_index"], 99.5)
        self.assertEqual(row["interval_start"], "2026-06-01T00:00:00Z")

    def test_negative_rate_kept_negative(self):
        row = ff.parse_row(raw("2026-06-01T00:00:00Z", "-0.0003"))
        self.assertEqual(row["funding_rate"], -0.0003)

    def test_missing_prices_become_none(self):
        row = ff.parse_row({"interval_start": "t", "funding_rate": 0.0001})
        self.assertIsNone(row["mark_price"])
        self.assertIsNone(row["price_index"])


class TestFetchHistory(unittest.TestCase):
    def test_follows_cursor_until_empty_page(self):
        api = FakeApi([
            {"data": [raw("A", "0.0001"), raw("B", "0.0002")], "pagination": {"cursor": "c1"}},
            {"data": [raw("C", "-0.0001")], "pagination": {"cursor": "c2"}},
            {"data": [], "pagination": {"cursor": "c3"}},
        ])
        rows = ff.fetch_history("BTCUC", "2026-01-01T00:00:00Z", get=api, limit=2)
        # 2 + 1 + 0 rows over 3 calls
        self.assertEqual([r["interval_start"] for r in rows], ["A", "B", "C"])
        self.assertEqual([r["funding_rate"] for r in rows], [0.0001, 0.0002, -0.0001])
        self.assertEqual(len(api.calls), 3)

    def test_first_call_params_and_cursor_passed_on(self):
        api = FakeApi([
            {"data": [raw("A", "0.0001")], "pagination": {"cursor": "c1"}},
            {"data": [], "pagination": {}},
        ])
        ff.fetch_history("BTCUC", "2026-01-01T00:00:00Z", get=api, limit=50)
        path, first = api.calls[0]
        self.assertEqual(path, "/funding-rates/")
        self.assertEqual(first, {"base_symbol": "BTCUC", "begin_time": "2026-01-01T00:00:00Z",
                                 "order": "asc", "limit": 50})
        self.assertEqual(api.calls[1][1]["cursor"], "c1")

    def test_stops_when_no_cursor(self):
        api = FakeApi([{"data": [raw("A", "0.0001")]}])
        rows = ff.fetch_history("BTCUC", "x", get=api)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(api.calls), 1)

    def test_stops_on_repeated_cursor(self):
        api = FakeApi([
            {"data": [raw("A", "0.0001")], "pagination": {"cursor": "same"}},
            {"data": [raw("B", "0.0001")], "pagination": {"cursor": "same"}},
            {"data": [raw("C", "0.0001")], "pagination": {"cursor": "same"}},
        ])
        rows = ff.fetch_history("BTCUC", "x", get=api)
        # page 1 sets last_cursor="same"; page 2 repeats it -> stop after 2 calls
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(len(rows), 2)

    def test_duplicates_removed_and_sorted_oldest_first(self):
        api = FakeApi([
            {"data": [raw("2026-06-02T00:00:00Z", "0.0002"),
                      raw("2026-06-01T00:00:00Z", "0.0001")], "pagination": {"cursor": "c1"}},
            {"data": [raw("2026-06-02T00:00:00Z", "0.0002"),
                      raw("2026-06-03T00:00:00Z", "0.0003")], "pagination": {}},
        ])
        rows = ff.fetch_history("BTCUC", "x", get=api)
        self.assertEqual([r["interval_start"] for r in rows],
                         ["2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", "2026-06-03T00:00:00Z"])

    def test_empty_first_page_returns_empty_list(self):
        api = FakeApi([{"data": [], "pagination": {"cursor": "c1"}}])
        self.assertEqual(ff.fetch_history("NOPE", "x", get=api), [])
        self.assertEqual(len(api.calls), 1)


class TestCsvAndFetchAll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_write_csv_round_trip(self):
        rows = [ff.parse_row(raw("A", "0.0001")), ff.parse_row(raw("B", "-0.0002"))]
        filename = os.path.join(self.tmp, "sub", "f.csv")
        ff.write_csv(rows, filename)
        with open(filename, newline="") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, ff.CSV_FIELDS)
            back = list(reader)
        self.assertEqual(len(back), 2)
        self.assertEqual(float(back[1]["funding_rate"]), -0.0002)

    def test_fetch_all_writes_one_file_per_coin_and_skips_blank(self):
        api = FakeApi([
            {"data": [raw("A", "0.0001"), raw("B", "0.0001")], "pagination": {}},
        ])
        counts = ff.fetch_all({"BTC": "BTCUC", "DOGE": ""}, "x", self.tmp, get=api)
        self.assertEqual(counts, {"BTC": 2})
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "funding_BTC.csv")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "funding_DOGE.csv")))

    def test_fetch_all_no_rows_writes_no_file(self):
        api = FakeApi([{"data": [], "pagination": {}}])
        counts = ff.fetch_all({"ETH": "WRONG"}, "x", self.tmp, get=api)
        self.assertEqual(counts, {"ETH": 0})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "funding_ETH.csv")))


class TestFindPerps(unittest.TestCase):
    def test_keeps_only_perps(self):
        specs = [{"symbol": "PBUCZ50", "product_name": "Bitcoin Perpetual"},
                 {"symbol": "BUSZ26", "product_name": "Bitcoin Dec 2026"},
                 {"symbol": "PETHZ50", "product_name": "Ether PERP"}]
        self.assertEqual([s["symbol"] for s in ff.find_perps(specs)], ["PBUCZ50", "PETHZ50"])


if __name__ == "__main__":
    unittest.main()
