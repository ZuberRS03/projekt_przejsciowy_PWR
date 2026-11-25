"""Testy dekodowania ruchu ESP32->laptop, w tym zmiany epoki zegara."""
import sys
import struct
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from receiver import Receiver, HEADER, IMU_SAMPLE, IMU_META, SHOT
from test_clock_sync import report_for


def make_packet(seq, kind, t_send, payload):
    return HEADER.pack(0x5052, 1, kind, seq, t_send) + payload


class ReceiverTests(unittest.TestCase):
    def test_live_flow_and_restart(self):
        r = Receiver()
        with redirect_stdout(StringIO()):
            for i in range(15):
                times = report_for(i)
                p = struct.pack('<qqqq', *times)
                r.accept_packet(make_packet(i, 5, times[3], p))
            self.assertTrue(r.sync.ready)
            self.assertEqual(r.missing_seq, 0)

            sample = IMU_SAMPLE.pack(21_000_000, 1, 2, 3, 4, 5, 6)
            r.accept_packet(make_packet(15, 1, 21_000_100,
                                        IMU_META.pack(1, 0, 0) + sample))
            self.assertEqual(r.last_imu[0], 21_000_000)
            self.assertIsNotNone(r.sync.to_rpi_ns(r.last_imu[0]))
            r.accept_packet(make_packet(16, 2, 21_100_000, SHOT.pack(7, 21_050_000, 0)))
            r.accept_packet(make_packet(17, 2, 21_100_100, SHOT.pack(7, 21_050_000, 1)))
            self.assertEqual(r.unique_shots, 1)
            self.assertEqual(r.duplicate_shots, 1)

            # Po restarcie stare dopasowanie nie moze byc uzyte ponownie.
            r.accept_packet(make_packet(0, 6, 100_000, struct.pack('<HbBI', 0, -40, 1, 0)))
            self.assertEqual(r.session, 2)
            self.assertFalse(r.sync.ready)
            self.assertEqual(len(r.seen_shots), 0)
        r.close()

    def test_bad_packet(self):
        r = Receiver()
        with self.assertRaises(ValueError):
            r.accept_packet(b'bad')
        r.close()


if __name__ == '__main__':
    unittest.main()
