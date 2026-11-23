"""Nadajnik klatek kamery RPi -> laptop (VIDEO_FRAME, specyfikacja §5.4, issue #15).

Wątek główny odbiera klatki z kamery (strumień lores 640x360, płaszczyzna Y8), kopiuje je raz
i oddaje do ograniczonej kolejki (przy przepełnieniu odrzucana jest najstarsza klatka).
Osobny wątek wysyła klatki przez ZeroMQ PUSH (tcp, bind). Strata klatki jest widoczna
po luce w frame_seq, a nagłówkowe seq jest ciągłe dla wysłanych wiadomości.
Co --stats-interval s jedna linia statystyk; SIGTERM / Ctrl+C kończą pracę łagodnie.
"""

from __future__ import annotations

import argparse
import signal
import statistics
import threading
import time
from collections import deque

import camera_config as cc
from protocol import monotonic_ns, pack_video_header


class DropOldestQueue:
    """Kolejka ograniczona: put() przy przepełnieniu odrzuca najstarszy element."""

    def __init__(self, maxlen):
        self._items = deque()
        self._maxlen = maxlen
        self._cond = threading.Condition()
        self.closed = False

    def put(self, item) -> bool:
        """Zwraca True, gdy odrzucono najstarszy element."""
        with self._cond:
            dropped = len(self._items) >= self._maxlen
            if dropped:
                self._items.popleft()
            self._items.append(item)
            self._cond.notify()
            return dropped

    def get(self, timeout=None):
        """Najstarszy element albo None po upływie timeout / zamknięciu pustej kolejki."""
        with self._cond:
            if not self._items and not self.closed:
                self._cond.wait(timeout)
            return self._items.popleft() if self._items else None

    def wait_empty(self, timeout) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._cond:
                if not self._items:
                    return True
            time.sleep(0.005)
        return False

    def close(self):
        with self._cond:
            self.closed = True
            self._items.clear()
            self._cond.notify_all()

    def __len__(self):
        return len(self._items)


class FrameCounter:
    """Numer klatki kamery z SensorTimestamp: 0, potem +max(1, round(dt / FrameDuration))."""

    def __init__(self):
        self._last_ts = None
        self.frame_seq = -1

    def next(self, t_sensor_ns, frame_duration_us) -> int:
        if self._last_ts is None:
            self.frame_seq = 0
        else:
            step = round((t_sensor_ns - self._last_ts) / (frame_duration_us * 1000))
            self.frame_seq = (self.frame_seq + max(1, step)) & 0xFFFFFFFF
        self._last_ts = t_sensor_ns
        return self.frame_seq


class Stats:
    """Liczniki całkowite i okno statystyk (zerowane po każdym wydruku); bezpieczne wątkowo."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = {"captured": 0, "sent": 0, "camera_drops": 0, "queue_drops": 0, "stale_drops": 0}
        self._reset()

    def _reset(self):
        self._ts = []
        self._capture_ms = []
        self._send_ms = []

    def add_capture(self, t_sensor_ns, latency_ms, camera_drops, queue_dropped):
        with self._lock:
            self.total["captured"] += 1
            self.total["camera_drops"] += camera_drops
            self.total["queue_drops"] += queue_dropped
            self._ts.append(t_sensor_ns)
            self._capture_ms.append(latency_ms)

    def add_stale(self):
        with self._lock:
            self.total["stale_drops"] += 1

    def add_send(self, ms):
        with self._lock:
            self.total["sent"] += 1
            self._send_ms.append(ms)

    def line(self, window_s):
        """Linia statystyk dla okna; zeruje okno."""
        with self._lock:
            ts, cap, snd, tot = self._ts, self._capture_ms, self._send_ms, dict(self.total)
            self._reset()
        fps = (len(ts) - 1) * 1e9 / (ts[-1] - ts[0]) if len(ts) > 1 and ts[-1] > ts[0] else 0.0

        def p50_max(v):
            return (statistics.median(v), max(v)) if v else (0.0, 0.0)

        c50, cmax = p50_max(cap)
        s50, smax = p50_max(snd)
        return (f"[video] fps={fps:.2f} wyslane={tot['sent']} camera_drops={tot['camera_drops']} "
                f"queue_drops={tot['queue_drops']} stale_drops={tot['stale_drops']} przechwycenie p50/max={c50:.2f}/{cmax:.2f} ms "
                f"wysylka p50/max={s50:.2f}/{smax:.2f} ms (okno {window_s:g} s)")


def sender_loop(sock, queue, stats, stop, log, max_age_ms=50.0):
    """Wątek wysyłający: seq rośnie dla każdej wysłanej wiadomości, t_send tuż przed wysyłką.

    Gdy nie ma odbiorcy (zmq.Again), klatka starsza niż max_age_ms jest porzucana (stale_drops),
    dzięki czemu po podłączeniu odbiorca dostaje świeże klatki.
    """
    import zmq

    seq = 0
    no_peer = False  # ostatnia próba wysyłki zakończyła się zmq.Again
    try:
        while not stop.is_set():
            item = queue.get(timeout=0.2)
            if item is None:
                continue
            frame_seq, t_sensor_ns, frame_duration_us, exposure_us, payload = item
            if no_peer and (monotonic_ns() - t_sensor_ns) / 1e6 > max_age_ms:
                stats.add_stale()  # bez odbiorcy nie próbuj wysyłać starych klatek z kolejki
                continue
            while not stop.is_set():
                t0 = monotonic_ns()  # t_send; przy ponowieniu (brak odbiorcy) odświeżany
                head = pack_video_header(seq, t0, frame_seq, t_sensor_ns, exposure_us, frame_duration_us,
                                         cc.LINE_TIME_NS, cc.LORES_SIZE[0], cc.LORES_SIZE[1], cc.SENSOR_ROWS)
                try:
                    sock.send_multipart([head, payload], copy=False)
                except zmq.Again:  # brak odbiorcy / pełny bufor
                    no_peer = True
                    # stara albo wyprzedzona nowszą klatką w kolejce: porzuć, by po podłączeniu nie było luki
                    if len(queue) or (monotonic_ns() - t_sensor_ns) / 1e6 > max_age_ms:
                        stats.add_stale()
                        break
                    continue
                no_peer = False
                stats.add_send((monotonic_ns() - t0) / 1e6)
                seq += 1
                break
    except Exception as exc:  # np. zmq.ZMQError
        log(f"[video] blad wysylki: {exc!r}")


def run(source, sock, queue_size=4, stats_interval=60.0, stop_event=None, seconds=0.0, log=print,
        max_age_ms=50.0):
    """Pętla przechwytywania. source: iterator krotek (t_sensor_ns, frame_duration_us, exposure_us, payload).

    Kończy się po wyczerpaniu source, po `seconds` albo po ustawieniu stop_event.
    Zwraca słownik z sumarycznymi statystykami (captured, sent, camera_drops, queue_drops).
    """
    import zmq

    sock.setsockopt(zmq.SNDTIMEO, 10)  # krótko: sender często sprawdza wiek klatki i stop
    stop_event = stop_event or threading.Event()
    sender_stop = threading.Event()
    queue = DropOldestQueue(queue_size)
    stats = Stats()
    counter = FrameCounter()
    sender = threading.Thread(target=sender_loop, args=(sock, queue, stats, sender_stop, log, max_age_ms), name="sender")
    sender.start()

    t_start = time.monotonic()
    last_stats = t_start
    last_fseq = None
    try:
        for t_sensor_ns, frame_duration_us, exposure_us, payload in source:
            t_capture_ns = monotonic_ns()  # tuż po zwróceniu klatki (wliczone jedno kopiowanie)
            frame_seq = counter.next(t_sensor_ns, frame_duration_us)
            camera_drops = 0 if last_fseq is None else max(0, frame_seq - last_fseq - 1)
            last_fseq = frame_seq
            dropped = queue.put((frame_seq, t_sensor_ns, frame_duration_us, exposure_us, payload))
            stats.add_capture(t_sensor_ns, (t_capture_ns - t_sensor_ns) / 1e6, camera_drops, int(dropped))
            now = time.monotonic()
            if now - last_stats >= stats_interval:
                log(stats.line(now - last_stats))
                last_stats = now
            if stop_event.is_set() or (seconds and now - t_start >= seconds):
                break
        else:  # koniec źródła (testy): daj wątkowi wysłać resztę kolejki
            queue.wait_empty(3.0)
    finally:
        close = getattr(source, "close", None)
        if close:
            close()  # zatrzymanie kamery
        queue.close()
        sender_stop.set()
        sender.join(timeout=3)
    log(stats.line(time.monotonic() - last_stats))
    log("[video] podsumowanie: " + " ".join(f"{k}={v}" for k, v in stats.total.items()))
    return stats.total


def picamera_source(exposure_us, gain, lens_position, warmup=30):
    """Generator klatek z Picamera2: (t_sensor_ns, frame_duration_us, exposure_us, bajty Y8)."""
    from picamera2 import MappedArray, Picamera2  # tylko na RPi

    picam2 = Picamera2()
    cc.configure(picam2, exposure_us, gain, lens_position)
    picam2.start()
    try:
        for _ in range(warmup):  # pierwsze klatki mają jeszcze nieustalone parametry
            picam2.capture_request().release()
        height = cc.LORES_SIZE[1]
        while True:
            request = picam2.capture_request()
            try:
                md = request.get_metadata()
                # MappedArray mapuje bufor DMA bez kopiowania (make_array kopiuje cały bufor 345 KB);
                # jedyne kopiowanie to 230 KB płaszczyzny Y (pierwsze 360 wierszy tablicy 540x640)
                with MappedArray(request, "lores") as m:
                    payload = m.array[:height].tobytes()
            finally:
                request.release()  # bufor DMA wraca do kamery natychmiast
            yield md["SensorTimestamp"], md["FrameDuration"], md["ExposureTime"], payload
    finally:
        picam2.stop()
        picam2.close()


def fake_source(fps=120.0):
    """Syntetyczne klatki bez kamery (test odbiornika na laptopie); wzór zmienia się z numerem klatki."""
    period_ns = int(1e9 / fps)
    size = cc.LORES_SIZE[0] * cc.LORES_SIZE[1]
    t0 = monotonic_ns()
    n = 0
    while True:
        t_sensor_ns = t0 + n * period_ns
        wait_s = (t_sensor_ns - monotonic_ns()) / 1e9
        if wait_s > 0:
            time.sleep(wait_s)
        yield t_sensor_ns, period_ns // 1000, cc.DEFAULT_EXPOSURE_US, bytes([n % 256]) * size
        n += 1


def main():
    import zmq

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="tcp://*:5555", help="adres ZeroMQ PUSH (bind)")
    parser.add_argument("--exposure-us", type=int, default=cc.DEFAULT_EXPOSURE_US, help="czas ekspozycji [us]")
    parser.add_argument("--gain", type=float, default=cc.DEFAULT_GAIN, help="wzmocnienie analogowe")
    parser.add_argument("--lens-position", type=float, default=cc.DEFAULT_LENS_POSITION,
                        help="dioptrie (1/m), 0 = nieskończoność")
    parser.add_argument("--queue-size", type=int, default=4, help="pojemność kolejki (drop-oldest)")
    parser.add_argument("--sndhwm", type=int, default=2, help="ZeroMQ SNDHWM (liczba wiadomości)")
    parser.add_argument("--max-age-ms", type=float, default=50,
                        help="maks. wiek klatki [ms] przy braku odbiorcy; starsze są porzucane (stale_drops)")
    parser.add_argument("--stats-interval", type=float, default=60, help="okres statystyk [s]")
    parser.add_argument("--seconds", type=float, default=0, help="czas pracy [s], 0 = do zatrzymania")
    parser.add_argument("--fake", action="store_true",
                        help="syntetyczne klatki 120 fps zamiast kamery (test bez picamera2)")
    args = parser.parse_args()

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDHWM, args.sndhwm)
    sock.setsockopt(zmq.LINGER, 0)
    sock.bind(args.bind)
    print(f"[video] bind {args.bind}, kolejka={args.queue_size}, sndhwm={args.sndhwm}", flush=True)
    source = fake_source() if args.fake else picamera_source(args.exposure_us, args.gain, args.lens_position)
    try:
        run(source, sock, args.queue_size, args.stats_interval, stop, args.seconds,
            log=lambda s: print(s, flush=True), max_age_ms=args.max_age_ms)
    finally:
        sock.close()
        ctx.term()
    print("[video] zatrzymano", flush=True)


if __name__ == "__main__":
    main()
