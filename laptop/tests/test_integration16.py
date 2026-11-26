"""End-to-end bez fizycznego sprzetu: raporty #14 -> SHOT -> VIDEO_FRAME."""
import io
import struct
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from correlation import Correlator, FrameInfo
from integrated_receiver import IntegratedUdpReceiver
from receiver import HEADER, SHOT
from test_clock_sync import report_for


def packet(seq, kind, t_send, payload):
    return HEADER.pack(0x5052, 1, kind, seq, t_send) + payload


class EndToEndTests(unittest.TestCase):
    def test_model_to_video_correlation(self):
        results = []
        c = Correlator(on_result=results.append)
        r = IntegratedUdpReceiver(c)
        with redirect_stdout(io.StringIO()):
            for i in range(20):
                ts = report_for(i)
                r.accept_packet(packet(i, 5, ts[3], struct.pack('<qqqq', *ts)))
            self.assertTrue(r.sync.ready)
            shot_t_us = 24_050_000
            shot_rpi_ns = r.sync.to_rpi_ns(shot_t_us)
            r.accept_packet(packet(20, 2, shot_t_us + 50, SHOT.pack(123, shot_t_us, 0)))
            self.assertEqual(len(results), 0)
            for j in range(7):
                ts = shot_rpi_ns - 23_000_000 + j * 8_333_000
                c.add_frame(FrameInfo(j, j, ts, 1000, 8333, 9209, 640, 360, 864))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'MATCH')
        self.assertEqual(results[0].shot.shot_id, 123)
        self.assertEqual(results[0].shot.t_rpi_ns, shot_rpi_ns)
        r.close()


if __name__ == '__main__':
    unittest.main()
