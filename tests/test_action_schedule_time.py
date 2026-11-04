"""Pure fixed-interval scheduling tests. No PostgreSQL or external tools needed."""
import unittest
from datetime import datetime, timedelta, timezone

from info_hub.action_schedule_time import next_cadence_time


class ActionScheduleTimeTests(unittest.TestCase):
    def setUp(self):
        self.due = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)

    def test_earlier_now_does_not_change_due(self):
        self.assertEqual(
            next_cadence_time(
                self.due, interval_minutes=60,
                now=self.due - timedelta(seconds=1),
            ), self.due,
        )

    def test_exact_due_advances_one_interval(self):
        self.assertEqual(
            next_cadence_time(self.due, interval_minutes=60, now=self.due),
            self.due + timedelta(hours=1),
        )

    def test_fractional_elapsed_time_advances_only_once(self):
        self.assertEqual(
            next_cadence_time(
                self.due, interval_minutes=60,
                now=self.due + timedelta(minutes=59, seconds=59),
            ), self.due + timedelta(hours=1),
        )

    def test_missed_windows_are_not_replayed(self):
        self.assertEqual(
            next_cadence_time(
                self.due, interval_minutes=30,
                now=self.due + timedelta(hours=4, minutes=12),
            ), self.due + timedelta(hours=4, minutes=30),
        )

    def test_exact_many_missed_boundaries_advances_past_now(self):
        self.assertEqual(
            next_cadence_time(
                self.due, interval_minutes=10,
                now=self.due + timedelta(hours=5),
            ), self.due + timedelta(hours=5, minutes=10),
        )

    def test_minute_interval(self):
        self.assertEqual(
            next_cadence_time(
                self.due, interval_minutes=1,
                now=self.due + timedelta(minutes=2, seconds=23),
            ), self.due + timedelta(minutes=3),
        )

    def test_weekly_interval(self):
        self.assertEqual(
            next_cadence_time(
                self.due, interval_minutes=10080,
                now=self.due + timedelta(days=24),
            ), self.due + timedelta(days=28),
        )

    def test_ignores_timezone_display_when_comparing_same_instant(self):
        different_offset = timezone(timedelta(hours=3))
        now = self.due.astimezone(different_offset)
        self.assertEqual(
            next_cadence_time(self.due, interval_minutes=120, now=now),
            self.due + timedelta(hours=2),
        )

    def test_rejects_out_of_bounds(self):
        for interval in (-1, 0, 10081, True, 0.5, "2"):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    next_cadence_time(self.due, interval_minutes=interval, now=self.due)

    def test_rejects_naive_datetimes(self):
        naive = self.due.replace(tzinfo=None)
        with self.assertRaises(ValueError):
            next_cadence_time(naive, interval_minutes=60, now=self.due)
        with self.assertRaises(ValueError):
            next_cadence_time(self.due, interval_minutes=60, now=naive)


if __name__ == "__main__":
    unittest.main()
