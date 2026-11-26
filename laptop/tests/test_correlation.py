"""Testy watermark, dwoch kolejnosci przyjscia, buforowania i diagnostyki #16."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from correlation import Correlator, FrameInfo, ImuInfo, ShotInfo, SyncQuality

T = 100_000_000_000


def frame(idx, *, t0=None, period_ns=8_333_000):
    start = (T - 25_000_000 if t0 is None else t0)
    return FrameInfo(idx, idx, start + idx * period_ns, 1000, 8333, 9209, 640, 360, 864)


def shot(sid=1, t=T):
    return ShotInfo(1, sid, 123_000_000, t, SyncQuality(25, 3200, 12, 150))


class CorrelationTests(unittest.TestCase):
    def test_watermark_waits_until_future_frame_and_links_imu(self):
        results = []
        c = Correlator(on_result=results.append)
        c.add_imu(ImuInfo(123, T + 1_000_000, (1, 2, 3), (4, 5, 6)))
        for i in range(3):
            c.add_frame(frame(i))
        c.add_shot(shot())
        self.assertEqual(len(results), 0)
        for i in range(3, 6):
            c.add_frame(frame(i))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'MATCH')
        self.assertEqual(results[0].shot.shot_id, 1)
        self.assertIsNotNone(results[0].imu)
        self.assertLess(abs(results[0].delta_ns), 10_000_000)

    def test_shot_after_future_frame_already_available(self):
        results = []
        c = Correlator(on_result=results.append)
        for i in range(7):
            c.add_frame(frame(i))
        c.add_shot(shot())
        self.assertEqual(results[0].status, 'MATCH')
        self.assertEqual(len(c.pending), 0)

    def test_unsynced_not_forced_into_match(self):
        results = []
        c = Correlator(on_result=results.append)
        for i in range(7):
            c.add_frame(frame(i))
        c.add_shot(ShotInfo(1, 4, 300, None, None))
        self.assertEqual(results[0].status, 'UNSYNCED')

    def test_no_near_frame_and_timeout(self):
        results = []
        c = Correlator(on_result=results.append, max_pending_s=2)
        for i in range(7):
            c.add_frame(frame(i))
        c.add_shot(shot(t=T - 800_000_000))
        self.assertEqual(results[-1].status, 'NO_NEAR_FRAME')
        c.add_shot(shot(sid=2, t=T + 1_000_000_000), now_ns=5)
        c.expire(now_ns=2_000_000_007)
        self.assertEqual(results[-1].status, 'VIDEO_TIMEOUT')

    def test_frame_gaps_and_reorder(self):
        c = Correlator()
        self.assertTrue(c.add_frame(frame(0)))
        self.assertTrue(c.add_frame(frame(3)))
        self.assertEqual(c.missing_frames, 2)
        self.assertEqual(c.missing_video_seq, 2)
        self.assertFalse(c.add_frame(frame(2)))
        self.assertEqual(c.out_of_order_frames, 1)

    def test_video_sender_restart_with_monotonic_clock(self):
        c = Correlator()
        for i in range(20):
            self.assertTrue(c.add_frame(frame(i)))
        new = FrameInfo(0, 0, c.last_sensor_ns + 8_333_000,
                        1000, 8333, 9209, 640, 360, 864)
        self.assertTrue(c.add_frame(new))
        self.assertEqual(c.frame_restarts, 1)
        self.assertEqual(c.missing_frames, 0)

    def test_esp_reset_clears_pending_not_frames(self):
        results = []
        c = Correlator(on_result=results.append)
        c.add_frame(frame(0))
        c.add_shot(shot(t=T + 1_000_000_000))
        c.reset_esp_session()
        self.assertEqual(len(c.frames), 1)
        self.assertEqual(len(c.pending), 0)
        self.assertEqual(results[0].status, 'ESP_RESTART')


if __name__ == '__main__':
    unittest.main()
