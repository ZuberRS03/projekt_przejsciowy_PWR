import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import protocol as pr  # noqa: E402
import video_receiver as vr  # noqa: E402
import video_sender as vs  # noqa: E402

try:
    import zmq
except ImportError:
    zmq = None

W, H = 640, 360
PERIOD_NS = 8_333_000


def header(seq=1, frame_seq=5, **over):
    kw = dict(magic=pr.MAGIC, version=pr.VERSION, typ=pr.TYPE_VIDEO_FRAME, fmt=pr.FORMAT_Y8, w=W, h=H)
    kw.update(over)
    return pr.VIDEO_FRAME_HEADER.pack(kw["magic"], kw["version"], kw["typ"], seq, 111, frame_seq, 222,
                                      2000, 8324, 9209, kw["w"], kw["h"], 864, kw["fmt"])


def message(seq, frame_seq, ts=0, payload=None):
    head = pr.pack_video_header(seq, 1, frame_seq, ts, 2000, 8324, 9209, W, H, 864)
    return [head, payload if payload is not None else bytes(W * H)]


class TestProtocol(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(pr.HEADER.size, 16)
        self.assertEqual(pr.VIDEO_META.size, 31)
        self.assertEqual(pr.VIDEO_FRAME_HEADER.size, 47)

    def test_round_trip(self):
        data = pr.pack_video_header(7, -5, 4_000_000_000, 123456789012, 2000, 8324, 9209, W, H, 864)
        self.assertEqual(len(data), 47)
        self.assertEqual(data[:2], b"\x52\x50")
        parsed = pr.parse_video_header(data)
        self.assertEqual(tuple(parsed), (7, -5, 4_000_000_000, 123456789012, 2000, 8324, 9209, W, H, 864, 1))

    def test_rejects(self):
        good = header()
        self.assertIsNotNone(pr.parse_video_header(good))
        for bad in (good[:46], good + b"\x00", b"", header(magic=0x1234), header(version=2),
                    header(typ=pr.TYPE_SYNC_REQ)):
            self.assertIsNone(pr.parse_video_header(bad))


class TestFrameCounter(unittest.TestCase):
    def test_steps_and_gap(self):
        c = vs.FrameCounter()
        ts = [0, 1, 2, 5, 6]  # luka 2 klatek między 2 a 5
        self.assertEqual([c.next(t * PERIOD_NS, 8333) for t in ts], [0, 1, 2, 5, 6])

    def test_jitter_is_one_step(self):
        c = vs.FrameCounter()
        t = 0
        seqs = [c.next(t, 8333)]
        for k in range(10):
            t += int(PERIOD_NS * (1.1 if k % 2 else 0.9))
            seqs.append(c.next(t, 8333))
        self.assertEqual(seqs, list(range(11)))

    def test_never_goes_backwards(self):
        c = vs.FrameCounter()
        c.next(1000, 8333)
        self.assertEqual(c.next(1000, 8333), 1)


class TestQueue(unittest.TestCase):
    def test_drop_oldest(self):
        q = vs.DropOldestQueue(3)
        self.assertEqual([q.put(i) for i in range(5)], [False, False, False, True, True])
        self.assertEqual([q.get(0.01) for _ in range(3)], [2, 3, 4])
        self.assertIsNone(q.get(0.01))

    def test_close_wakes_getter(self):
        q = vs.DropOldestQueue(2)
        threading.Timer(0.05, q.close).start()
        t0 = time.monotonic()
        self.assertIsNone(q.get(2))
        self.assertLess(time.monotonic() - t0, 1)


class TestFrameStats(unittest.TestCase):
    def test_clean_stream(self):
        s = vr.FrameStats()
        for i in range(10):
            self.assertTrue(s.add(message(i, i, i * PERIOD_NS), i * 0.00833))
        self.assertEqual((s.frames, s.invalid, s.seq_gaps, s.missing_frames), (10, 0, 0, 0))
        self.assertAlmostEqual(s.fps, 120.05, delta=0.2)
        self.assertTrue(s.ok())
        self.assertIn("WYNIK: OK", s.summary())

    def test_gaps(self):
        s = vr.FrameStats()
        s.add(message(0, 0), 0.0)
        s.add(message(1, 3), 0.1)   # brak klatek 1 i 2
        s.add(message(3, 4), 0.2)   # brak wiadomosci seq 2
        self.assertEqual((s.seq_gaps, s.missing_frames), (1, 2))
        self.assertFalse(s.ok())
        self.assertIn("WYNIK: BLAD", s.summary())

    def test_threshold(self):
        s = vr.FrameStats()
        for i in range(200):
            s.add(message(i, i + (1 if i >= 100 else 0)), i * 0.01)  # 1 brakujaca na 201 = 0.50%
        self.assertEqual(s.missing_frames, 1)
        self.assertTrue(s.ok())

    def test_invalid(self):
        s = vr.FrameStats()
        good = message(0, 0)
        for parts in ([good[0]], [good[0], b"x" * 10], [header(fmt=2), bytes(W * H)], [b"abc", b"def"]):
            self.assertFalse(s.add(parts, 0.0))
        self.assertEqual((s.messages, s.invalid, s.frames), (4, 4, 0))
        self.assertFalse(s.ok())

    def test_save_pgm(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.pgm")
            vr.save_pgm(path, 4, 2, bytes(range(8)))
            self.assertEqual(open(path, "rb").read(), b"P5\n4 2\n255\n" + bytes(range(8)))


@unittest.skipUnless(zmq, "brak pyzmq")
class TestEndToEnd(unittest.TestCase):
    def test_send_receive(self):
        n_frames = 20
        indices = [i for i in range(n_frames + 2) if i not in (10, 11)]  # luka 2 klatek przed 12

        def source():
            for i in indices:
                time.sleep(0.002)
                yield i * PERIOD_NS, 8333, 2000, bytes([i]) * (W * H)

        ctx = zmq.Context()
        push = ctx.socket(zmq.PUSH)
        push.setsockopt(zmq.LINGER, 0)
        push.bind("tcp://127.0.0.1:*")
        endpoint = push.getsockopt(zmq.LAST_ENDPOINT).decode()
        pull = ctx.socket(zmq.PULL)
        pull.setsockopt(zmq.LINGER, 0)
        pull.setsockopt(zmq.RCVTIMEO, 2000)
        pull.connect(endpoint)
        result = {}
        thread = threading.Thread(
            target=lambda: result.update(vs.run(source(), push, queue_size=64, log=lambda s: None)))
        t0 = time.monotonic()
        thread.start()
        try:
            received = [pull.recv_multipart() for _ in range(n_frames)]
        finally:
            thread.join(timeout=5)
            pull.close()
            push.close()
            ctx.term()
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual((result["sent"], result["queue_drops"], result["camera_drops"]), (n_frames, 0, 2))

        stats = vr.FrameStats()
        headers = []
        for k, parts in enumerate(received):
            self.assertTrue(stats.add(parts, k * 0.01))
            headers.append(pr.parse_video_header(parts[0]))
            self.assertEqual(parts[1], bytes([indices[k]]) * (W * H))
        self.assertEqual([h.seq for h in headers], list(range(n_frames)))
        self.assertEqual([h.frame_seq for h in headers], indices)
        self.assertEqual(stats.missing_frames, 2)
        self.assertEqual(stats.seq_gaps, 0)
        self.assertEqual(headers[0].line_time_ns, 9209)
        self.assertEqual((headers[0].width, headers[0].height, headers[0].sensor_rows), (W, H, 864))
        self.assertTrue(all(b.t_send_ns >= a.t_send_ns for a, b in zip(headers, headers[1:])))

    def test_stale_frames_dropped_without_peer(self):
        ctx = zmq.Context()
        push = ctx.socket(zmq.PUSH)
        push.setsockopt(zmq.LINGER, 0)
        push.bind("tcp://127.0.0.1:*")
        endpoint = push.getsockopt(zmq.LAST_ENDPOINT).decode()
        now = vs.monotonic_ns()
        old = now - 10_000_000_000
        state = {}

        def source():
            for i in range(3):  # stare klatki, brak odbiorcy (porzucane po ~50 ms)
                yield old + i * PERIOD_NS, 8333, 2000, bytes([i]) * (W * H)
            time.sleep(0.5)  # sender zdazy porzucic stare klatki
            state["pull"] = pull = ctx.socket(zmq.PULL)
            pull.setsockopt(zmq.LINGER, 0)
            pull.setsockopt(zmq.RCVTIMEO, 2000)
            pull.connect(endpoint)
            time.sleep(0.5)  # połączenie
            for i in range(3, 13):  # świeże klatki
                time.sleep(0.002)
                yield vs.monotonic_ns(), 8333, 2000, bytes([i]) * (W * H)

        result = {}
        thread = threading.Thread(target=lambda: result.update(
            vs.run(source(), push, queue_size=64, log=lambda s: None, max_age_ms=50)))
        thread.start()
        thread.join(timeout=8)
        pull = state["pull"]
        try:
            received = [pull.recv_multipart() for _ in range(10)]
        finally:
            pull.close()
            push.close()
            ctx.term()
        self.assertEqual(result["stale_drops"], 3)
        self.assertEqual(result["sent"], 10)
        headers = [pr.parse_video_header(p[0]) for p in received]
        fseqs = [h.frame_seq for h in headers]
        self.assertEqual(fseqs, list(range(fseqs[0], fseqs[0] + 10)))  # bez luk wsrod odebranych
        self.assertEqual([h.seq for h in headers], list(range(10)))
        self.assertEqual([p[1][0] for p in received], list(range(3, 13)))


if __name__ == "__main__":
    unittest.main()
