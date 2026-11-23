"""Odbiornik diagnostyczny VIDEO_FRAME na laptopie (specyfikacja §5.4, test T3, issue #15).

Łączy się jako ZeroMQ PULL z nadajnikiem na RPi, sprawdza każdą wiadomość (nagłówek, format,
rozmiar obrazu) i liczy straty po nagłówkowym seq oraz po frame_seq, FPS, przepustowość
i okres klatek z t_sensor_ns. Opóźnienia nadawcy nie da się policzyć (różne zegary).
Kod wyjścia 0 = brak błędnych wiadomości, utracone klatki <= 0,5% i odebrano co najmniej jedną klatkę.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from protocol import FORMAT_Y8, parse_video_header

MAX_MISSING_PCT = 0.5  # kryterium T3


def missing_before(seq, expected):
    """Liczba brakujących numerów między oczekiwanym a odebranym (u32); cofnięcie = restart nadawcy."""
    gap = (seq - expected) & 0xFFFFFFFF
    return 0 if gap >= 0x80000000 else gap


class FrameStats:
    """Walidacja i statystyki odbieranych wiadomości; bez sieci, czas odbioru podawany z zewnątrz."""

    def __init__(self):
        self.messages = 0
        self.invalid = 0
        self.seq_gaps = 0       # brakujące wiadomości wg nagłówkowego seq
        self.missing_frames = 0  # brakujące klatki wg frame_seq
        self.frames = 0
        self.bytes = 0
        self.last_frame = None  # (width, height, dane) ostatniej poprawnej klatki
        self._next_seq = None
        self._next_frame_seq = None
        self._first_ts = self._last_ts = None
        self._first_rx = self._last_rx = None
        self._periods_ms = []

    def add(self, parts, rx_time_s) -> bool:
        """Przetwarza wiadomość multipart; zwraca True, gdy poprawna."""
        self.messages += 1
        header = parse_video_header(parts[0]) if len(parts) == 2 else None
        if (header is None or header.format != FORMAT_Y8
                or len(parts[1]) != header.width * header.height):
            self.invalid += 1
            return False
        if self._next_seq is not None:
            self.seq_gaps += missing_before(header.seq, self._next_seq)
            self.missing_frames += missing_before(header.frame_seq, self._next_frame_seq)
            self._periods_ms.append((header.t_sensor_ns - self._last_ts) / 1e6)
        else:
            self._first_ts = header.t_sensor_ns
            self._first_rx = rx_time_s
        self._next_seq = (header.seq + 1) & 0xFFFFFFFF
        self._next_frame_seq = (header.frame_seq + 1) & 0xFFFFFFFF
        self._last_ts = header.t_sensor_ns
        self._last_rx = rx_time_s
        self.frames += 1
        self.bytes += len(parts[0]) + len(parts[1])
        self.last_frame = (header.width, header.height, parts[1])
        return True

    @property
    def missing_pct(self):
        total = self.frames + self.missing_frames
        return 100 * self.missing_frames / total if total else 0.0

    @property
    def fps(self):
        span = (self._last_ts - self._first_ts) / 1e9 if self.frames > 1 else 0
        return (self.frames - 1) / span if span > 0 else 0.0

    @property
    def mbit_s(self):
        span = self._last_rx - self._first_rx if self.frames > 1 else 0
        return self.bytes * 8 / 1e6 / span if span > 0 else 0.0

    def ok(self) -> bool:
        return self.frames > 0 and self.invalid == 0 and self.missing_pct <= MAX_MISSING_PCT

    def summary(self) -> str:
        p = self._periods_ms
        period = f"p50={statistics.median(p):.2f} max={max(p):.2f} ms" if p else "brak danych"
        return "\n".join([
            f"Wiadomosci:          {self.messages} (bledne: {self.invalid})",
            f"Poprawne klatki:     {self.frames}",
            f"Luki seq naglowka:   {self.seq_gaps}",
            f"Brakujace klatki:    {self.missing_frames} ({self.missing_pct:.2f}%, limit {MAX_MISSING_PCT}%)",
            f"FPS (t_sensor):      {self.fps:.2f}",
            f"Przepustowosc:       {self.mbit_s:.1f} Mbit/s",
            f"Okres t_sensor:      {period}",
            f"WYNIK: {'OK' if self.ok() else 'BLAD'}",
        ])


def save_pgm(path, width, height, data):
    """Zapisuje obraz Y8 jako binarny PGM (P5)."""
    with open(path, "wb") as f:
        f.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        f.write(data)


def main():
    import zmq

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", default="tcp://192.168.50.10:5555", help="adres nadajnika (ZeroMQ PULL)")
    parser.add_argument("--seconds", type=float, default=10, help="czas odbioru od pierwszej klatki [s]")
    parser.add_argument("--timeout", type=float, default=5, help="maks. cisza w strumieniu [s]")
    parser.add_argument("--save-pgm", metavar="PATH", help="zapis ostatniej klatki jako PGM (P5)")
    args = parser.parse_args()

    ctx = zmq.Context()
    sock = ctx.socket(zmq.PULL)
    sock.setsockopt(zmq.RCVHWM, 8)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 100)
    sock.connect(args.connect)
    print(f"[odbiornik] polaczono z {args.connect}, odbior {args.seconds:g} s", flush=True)

    stats = FrameStats()
    last_rx = time.monotonic()
    t_first = None
    try:
        while True:
            now = time.monotonic()
            if t_first is not None and now - t_first >= args.seconds:
                break
            if now - last_rx > args.timeout:
                print(f"[odbiornik] brak danych przez {args.timeout:g} s", flush=True)
                break
            try:
                parts = sock.recv_multipart()
            except zmq.Again:
                continue
            last_rx = time.monotonic()
            t_first = t_first or last_rx
            stats.add(parts, last_rx)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        ctx.term()

    print(stats.summary())
    if args.save_pgm and stats.last_frame:
        save_pgm(args.save_pgm, *stats.last_frame)
        print(f"Zapisano ostatnia klatke: {args.save_pgm}")
    return 0 if stats.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
