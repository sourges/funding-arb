import csv
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import main_monitor as mm
import monitor


def frow(start, rate, mark, index=None):
    return {"interval_start": start, "interval_end": "", "funding_rate": rate,
            "mark_price": mark, "price_index": mark if index is None else index}


ENTRY = frow("2026-11-06T01:00:00Z", 0.0001, 2000.0)   # qty = 1000 / 2000 = 0.5


def fresh():
    return monitor.new_state(ENTRY, 1000.0)


class TestNewStateAndCushion(unittest.TestCase):
    def test_new_state(self):
        st = fresh()
        self.assertEqual(st["qty"], 0.5)
        self.assertEqual(st["entry_mark"], 2000.0)
        self.assertEqual(st["last_interval"], "2026-11-06T01:00:00Z")
        self.assertEqual(st["total_funding"], 0.0)   # entry row's funding not counted

    def test_cushion_values(self):
        st = fresh()
        # price 2000: equity 740, maint 0.157*0.5*2000 = 157 -> 583
        self.assertAlmostEqual(monitor.cushion(st, 2000.0, 740.0, 0.157), 583.0)
        # price 2500: equity 740 - 0.5*500 = 490, maint 196.25 -> 293.75
        self.assertAlmostEqual(monitor.cushion(st, 2500.0, 740.0, 0.157), 293.75)
        # price 3000: equity 240, maint 235.5 -> 4.5
        self.assertAlmostEqual(monitor.cushion(st, 3000.0, 740.0, 0.157), 4.5)

    def test_cushion_grows_when_price_falls(self):
        # price 1500: equity 740 + 250 = 990, maint 117.75 -> 872.25
        self.assertAlmostEqual(monitor.cushion(fresh(), 1500.0, 740.0, 0.157), 872.25)


class TestProcessRows(unittest.TestCase):
    def test_adds_new_rows_only(self):
        st = fresh()
        rows = [ENTRY,                                               # old -> skipped
                frow("2026-11-06T09:00:00Z", 0.0001, 2000.0),        # 0.0001*0.5*2000 = 0.1
                frow("2026-11-06T17:00:00Z", 0.0003, 2100.0)]        # 0.0003*0.5*2100 = 0.315
        log_rows, events = monitor.process_rows(st, rows, 0.0001)
        self.assertEqual(len(log_rows), 2)
        self.assertAlmostEqual(log_rows[0]["funding_earned"], 0.1)
        self.assertAlmostEqual(log_rows[1]["total_funding"], 0.415)
        self.assertAlmostEqual(st["total_funding"], 0.415)
        self.assertEqual(st["intervals"], 2)
        self.assertEqual(st["last_interval"], "2026-11-06T17:00:00Z")
        self.assertEqual(st["off_baseline"], 1)
        self.assertEqual([e[0] for e in events], ["off_baseline"])
        self.assertEqual(events[0][1]["funding_rate"], 0.0003)

    def test_same_rows_twice_counts_once(self):
        st = fresh()
        rows = [frow("2026-11-06T09:00:00Z", 0.0001, 2000.0)]
        monitor.process_rows(st, rows, 0.0001)
        log_rows, events = monitor.process_rows(st, rows, 0.0001)
        self.assertEqual(log_rows, [])
        self.assertAlmostEqual(st["total_funding"], 0.1)
        self.assertEqual(st["intervals"], 1)

    def test_gap_detected(self):
        st = fresh()
        st["last_interval"] = "2026-11-06T17:00:00Z"
        # last 11-06 17:00, next arrives 11-07 17:00: 11-07 01:00 and 09:00 missing = 2
        log_rows, events = monitor.process_rows(
            st, [frow("2026-11-07T17:00:00Z", 0.0001, 2000.0)], 0.0001)
        self.assertEqual(events, [("gap", 2)])
        self.assertEqual(st["gaps"], 2)
        self.assertEqual(len(log_rows), 1)

    def test_no_gap_for_next_interval(self):
        st = fresh()
        _, events = monitor.process_rows(st, [frow("2026-11-06T09:00:00Z", 0.0001, 2000.0)], 0.0001)
        self.assertEqual(events, [])
        self.assertEqual(st["gaps"], 0)

    def test_negative_rate_reduces_total_and_alerts(self):
        st = fresh()
        # -0.0002 * 0.5 * 2000 = -0.2
        _, events = monitor.process_rows(st, [frow("2026-11-06T09:00:00Z", -0.0002, 2000.0)], 0.0001)
        self.assertAlmostEqual(st["total_funding"], -0.2)
        self.assertIn("NEGATIVE", monitor.event_message(events[0]))


class TestAlertsAndSummary(unittest.TestCase):
    def test_cushion_alert_once_then_reset(self):
        st = fresh()
        self.assertEqual(monitor.check_cushion(st, 140.0, 150.0, 200.0), "low")
        self.assertIsNone(monitor.check_cushion(st, 120.0, 150.0, 200.0))   # still low, no repeat
        self.assertIsNone(monitor.check_cushion(st, 160.0, 150.0, 200.0))   # not yet above 200
        self.assertEqual(monitor.check_cushion(st, 210.0, 150.0, 200.0), "ok")
        self.assertIsNone(monitor.check_cushion(st, 210.0, 150.0, 200.0))

    def test_exactly_at_alert_level_no_alert(self):
        self.assertIsNone(monitor.check_cushion(fresh(), 150.0, 150.0, 200.0))

    def test_summary_due(self):
        st = fresh()
        self.assertFalse(monitor.summary_due(st, datetime(2026, 11, 7, 8, 59), 9))
        self.assertTrue(monitor.summary_due(st, datetime(2026, 11, 7, 9, 0), 9))
        st["last_summary_date"] = "2026-11-07"
        self.assertFalse(monitor.summary_due(st, datetime(2026, 11, 7, 15, 0), 9))
        self.assertTrue(monitor.summary_due(st, datetime(2026, 11, 8, 9, 5), 9))

    def test_error_alert_once_after_four(self):
        st = fresh()
        self.assertEqual([monitor.record_error(st, 4) for _ in range(5)],
                         [False, False, False, True, False])
        self.assertTrue(monitor.record_success(st))      # recovered from alerted streak
        self.assertFalse(monitor.record_success(st))
        self.assertEqual(st["consecutive_errors"], 0)

    def test_short_error_streak_no_recovery_message(self):
        st = fresh()
        monitor.record_error(st, 4)
        self.assertFalse(monitor.record_success(st))

    def test_days_running_starts_at_end_of_entry_interval(self):
        # entry interval 01:00 -> position opens 09:00 Nov 6; Nov 8 09:00 = 2.0 days
        now = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
        self.assertAlmostEqual(monitor.days_running(fresh(), now), 2.0)

    def test_summary_pace(self):
        st = fresh()
        st["total_funding"] = 0.415
        now = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
        # 0.415 / 2 days * 365 = 75.74 -> "$76/yr"
        text = monitor.summary_message(st, 2100.0, 500.0, now, 0.0001)
        self.assertIn("$0.41", text)        # float 0.415 is 0.41499..., rounds to $0.41
        self.assertIn("~$76/yr", text)
        self.assertIn("2.0 days", text)


class TestMainHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_state_round_trip_and_missing(self):
        path = os.path.join(self.tmp, "state.json")
        self.assertIsNone(mm.load_state(path))
        mm.save_state(fresh(), path)
        self.assertEqual(mm.load_state(path)["qty"], 0.5)
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_append_log_writes_header_once(self):
        path = os.path.join(self.tmp, "log.csv")
        row = {"interval_start": "a", "funding_rate": 0.0001, "mark_price": 2000.0,
               "funding_earned": 0.1, "total_funding": 0.1}
        mm.append_log([row], path)
        mm.append_log([dict(row, interval_start="b")], path)
        with open(path, newline="") as f:
            back = list(csv.DictReader(f))
        self.assertEqual([r["interval_start"] for r in back], ["a", "b"])

    def test_kraken_price_parses_last_trade(self):
        fake = mock.Mock()
        fake.json.return_value = {"error": [], "result": {"XETHZUSD": {"c": ["2234.51", "0.1"]}}}
        with mock.patch("main_monitor.requests.get", return_value=fake):
            self.assertEqual(mm.kraken_price("ETHUSD"), 2234.51)

    def test_kraken_price_error_raises(self):
        fake = mock.Mock()
        fake.json.return_value = {"error": ["EQuery:Unknown asset pair"], "result": {}}
        with mock.patch("main_monitor.requests.get", return_value=fake):
            with self.assertRaises(RuntimeError):
                mm.kraken_price("NOPE")


if __name__ == "__main__":
    unittest.main()
