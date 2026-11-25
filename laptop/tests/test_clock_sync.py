"""Testy modelu bez ESP32 i RPi: python -m unittest discover -s laptop/tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clock_sync import ClockSynchronizer


def report_for(i: int, a: float = 1.000015,
               b: float = 45_000_000_000.0,
               one_way_us: int = 1500,
               processing_us: int = 20):
    t1 = 5_000_000 + i * 1_000_000
    t4 = t1 + 2 * one_way_us + processing_us
    t2 = round((a * (t1 + one_way_us) + b) * 1000)
    t3 = round((a * (t1 + one_way_us + processing_us) + b) * 1000)
    return t1, t2, t3, t4


class ClockTests(unittest.TestCase):
    def test_not_ready_before_ten(self):
        model = ClockSynchronizer()
        for i in range(9):
            self.assertTrue(model.add_report(*report_for(i)))
        self.assertFalse(model.ready)
        self.assertIsNone(model.to_rpi_ns(7_000_000))

    def test_linear_drift_and_offset(self):
        a, b = 1.000015, 45_000_000_000.0
        model = ClockSynchronizer()
        for i in range(40):
            self.assertTrue(model.add_report(*report_for(i, a, b)))
        self.assertTrue(model.ready)
        self.assertAlmostEqual(model.fit.a, a, places=8)
        self.assertAlmostEqual(model.fit.drift_ppm, 15.0, delta=0.01)
        t = 20_000_000
        self.assertAlmostEqual(model.to_rpi_ns(t) / 1000, a * t + b, delta=0.05)

    def test_filter_out_high_rtt(self):
        model = ClockSynchronizer()
        for i in range(20):
            # Jeden kierunek opozniony o kilkadziesiat ms, co zaburza midpoint.
            extra = 10_000 if i in (4, 9, 15) else 0
            t1, t2, t3, t4 = report_for(i, one_way_us=1500 + extra)
            # Przesuniecie t4 zostaje, ale t2 opoznimy tylko o nominalne 1500us
            # -> duze RTT i niezgodny srodek, powinien trafic poza filtr.
            if extra:
                t2 -= extra * 1000
                t3 -= extra * 1000
            self.assertTrue(model.add_report(t1, t2, t3, t4))
        self.assertTrue(model.ready)
        self.assertEqual(model.fit.samples_used, 17)
        self.assertAlmostEqual(model.fit.drift_ppm, 15.0, delta=0.01)

    def test_window_60s(self):
        model = ClockSynchronizer()
        for i in range(75):
            model.add_report(*report_for(i))
        self.assertLessEqual(len(model.points), 61)
        self.assertTrue(model.ready)
        self.assertEqual(model.points[-1].esp_mid_us - model.points[0].esp_mid_us,
                         60_000_000)

    def test_reject_bad_order(self):
        model = ClockSynchronizer()
        t1, t2, t3, t4 = report_for(0)
        self.assertFalse(model.add_report(t4, t2, t3, t1))
        self.assertFalse(model.add_report(t1, t3, t2, t4))
        self.assertTrue(model.add_report(t1, t2, t3, t4))
        self.assertFalse(model.add_report(t1, t2, t3, t4))

    def test_stale_model_expires_without_new_sync_reports(self):
        model = ClockSynchronizer()
        for i in range(20):
            model.add_report(*report_for(i))
        self.assertTrue(model.ready)
        model.expire(5_000_000 + 81_000_000)
        self.assertFalse(model.ready)
        self.assertEqual(len(model.points), 0)

    def test_reset_epoch(self):
        model = ClockSynchronizer()
        for i in range(15):
            model.add_report(*report_for(i))
        self.assertTrue(model.ready)
        model.reset()
        self.assertFalse(model.ready)
        self.assertEqual(len(model.points), 0)
        self.assertEqual(model.restarts, 1)
        self.assertIsNone(model.to_rpi_ns(1_000_000))


if __name__ == '__main__':
    unittest.main()
