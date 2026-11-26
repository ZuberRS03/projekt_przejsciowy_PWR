"""Zgodnosc bitowa z rpi/protocol.py oraz odbior ZeroMQ multipart."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_stream import FRAME_HEADER, VideoPump, decode_parts


def make_frame(seq=1, frame_seq=2, t=10_000_000_000, width=8, height=4):
    return [FRAME_HEADER.pack(0x5052, 1, 16, seq, t+1000, frame_seq, t,
                              1000, 8333, 9209, width, height, 864, 1),
            bytes([123]) * (width * height)]


class VideoTests(unittest.TestCase):
    def test_format_47_bytes_exact(self):
        self.assertEqual(FRAME_HEADER.size, 47)
        frm = decode_parts(make_frame())
        self.assertEqual(frm.frame_seq, 2)
        self.assertEqual(frm.t_sensor_ns, 10_000_000_000)
        self.assertGreater(frm.t_center_ns(), frm.t_sensor_ns)

    def test_malformed_header_or_payload(self):
        msg = make_frame()
        with self.assertRaises(ValueError):
            decode_parts([msg[0], msg[1][:-1]])
        with self.assertRaises(ValueError):
            decode_parts([msg[0]])
        with self.assertRaises(ValueError):
            decode_parts([b'wrong' + msg[0][5:], msg[1]])

    def test_zmq_local_receive(self):
        import zmq
        ctx = zmq.Context()
        push = ctx.socket(zmq.PUSH)
        port = push.bind_to_random_port('tcp://127.0.0.1')
        pump = VideoPump(f'tcp://127.0.0.1:{port}')
        pump.start()
        try:
            time.sleep(.15)
            push.send_multipart(make_frame())
            result = pump.queue.get(timeout=2)
            self.assertEqual(result.seq, 1)
            self.assertEqual(pump.invalid, 0)
        finally:
            pump.stop()
            push.close(0)
            ctx.term()


if __name__ == '__main__':
    unittest.main()
