import os
import socket
import sys
import threading
import unittest
from itertools import count

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sync_responder as sr  # noqa: E402


def req(seq=1, t1=100, magic=sr.MAGIC, version=sr.VERSION, typ=sr.TYPE_SYNC_REQ):
    return sr.HEADER.pack(magic, version, typ, seq, t1)


class TestProtocol(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(sr.HEADER.size, 16)
        self.assertEqual(sr.SYNC_RESP.size, 32)

    def test_parse_ok(self):
        self.assertEqual(sr.parse_sync_req(req(7, -5)), (7, -5))

    def test_parse_rejects(self):
        good = req()
        for bad in (good[:15], good + b"\x00", good + bytes(16), req(magic=0x1234),
                    req(version=2), req(typ=sr.TYPE_SYNC_RESP), b""):
            self.assertIsNone(sr.parse_sync_req(bad))

    def test_build_layout(self):
        data = sr.build_sync_resp(0xAABBCCDD, 1234, 5_000_000_000, 5_000_000_100)
        self.assertEqual(len(data), 32)
        self.assertEqual(data[:2], b"\x52\x50")
        magic, version, typ, seq, t3, t1, t2 = sr.SYNC_RESP.unpack(data)
        self.assertEqual((magic, version, typ, seq), (0x5052, 1, 4, 0xAABBCCDD))
        self.assertEqual((t3, t1, t2), (5_000_000_100, 1234, 5_000_000_000))


class TestServer(unittest.TestCase):
    def setUp(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.bind(("127.0.0.1", 0))
        self.stop = threading.Event()
        ticks = count(1000, 10)
        self.thread = threading.Thread(
            target=sr.serve,
            kwargs=dict(sock=self.server, clock=lambda: next(ticks),
                        stop_event=self.stop, log=lambda s: None))
        self.thread.start()
        self.client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client.settimeout(0.3)
        self.client.connect(self.server.getsockname())

    def tearDown(self):
        self.stop.set()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.client.close()
        self.server.close()

    def exchange(self, seq, t1):
        self.client.send(req(seq, t1))
        return sr.SYNC_RESP.unpack(self.client.recv(64))

    def test_replies(self):
        prev_t2 = 0
        for seq, t1 in ((1, 111), (2, 222), (4000000000, -333)):
            magic, version, typ, r_seq, t3, r_t1, t2 = self.exchange(seq, t1)
            self.assertEqual((magic, version, typ), (sr.MAGIC, 1, 4))
            self.assertEqual((r_seq, r_t1), (seq, t1))
            self.assertLess(t2, t3)
            self.assertGreater(t2, prev_t2)
            prev_t2 = t2

    def test_malformed_ignored(self):
        self.client.send(req(magic=0xBEEF))
        self.client.send(req()[:15])
        self.client.send(req() + bytes(84))  # 100 B
        with self.assertRaises(socket.timeout):
            self.client.recv(64)
        self.assertEqual(self.exchange(9, 99)[3], 9)


if __name__ == "__main__":
    unittest.main()
