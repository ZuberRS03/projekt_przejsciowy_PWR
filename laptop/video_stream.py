"""Odbiornik ZeroMQ PULL VIDEO_FRAME z RPi na laptopie (issue #16).

Watek odbiera / sprawdza multipart bez kopiowania calego obrazu do kolejki;
wystawia tylko metadane. Opcjonalnie zachowuje ostatni obraz w PGM, aby
sprawdzic odtworzenie surowych pikseli.
"""
from __future__ import annotations

import queue
import struct
import threading
from pathlib import Path

from correlation import FrameInfo

MAGIC = 0x5052
VERSION = 1
TYPE_VIDEO_FRAME = 16
FORMAT_Y8 = 1
# rpi/protocol.py: HEADER '<HBBIq' + VIDEO_META '<IqIIIHHHB' = 47 B
FRAME_HEADER = struct.Struct('<HBBIqIqIIIHHHB')


def decode_parts(parts) -> FrameInfo:
    if len(parts) != 2 or len(parts[0]) != FRAME_HEADER.size:
        raise ValueError('VIDEO_FRAME: oczekiwane 2 czesci, naglowek 47 B')
    (magic, version, kind, seq, _t_send_ns, frame_seq, t_sensor_ns,
     exposure_us, duration_us, line_time_ns, width, height, rows, fmt) = FRAME_HEADER.unpack(bytes(parts[0]))
    if magic != MAGIC or version != VERSION or kind != TYPE_VIDEO_FRAME:
        raise ValueError('VIDEO_FRAME: magic, wersja lub typ nieprawidlowy')
    if fmt != FORMAT_Y8 or not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError('VIDEO_FRAME: nieobslugiwany format lub rozdzielczosc')
    if len(parts[1]) != width * height:
        raise ValueError('VIDEO_FRAME: rozmiar danych Y8 niezgodny z metadanymi')
    if t_sensor_ns <= 0 or duration_us <= 0 or rows < height:
        raise ValueError('VIDEO_FRAME: nieprawidlowe metadane czasu lub sensora')
    return FrameInfo(seq, frame_seq, t_sensor_ns, exposure_us, duration_us,
                     line_time_ns, width, height, rows)


def save_pgm(path: Path, width: int, height: int, pixels: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.write(f'P5\n{width} {height}\n255\n'.encode('ascii'))
        f.write(pixels)


class VideoPump:
    """Odbior PULL na osobnym watku, diagnostyka drop-oldest kolejki metadanych."""

    def __init__(self, connect: str, max_queue: int = 512,
                 save_last_pgm: str | None = None):
        self.connect = connect
        self.queue: queue.Queue[FrameInfo] = queue.Queue(maxsize=max_queue)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name='ZeroMQ-video', daemon=True)
        self.received = 0
        self.invalid = 0
        self.queue_drops = 0
        self.errors = 0
        self.last_error = ''
        self.save_path = Path(save_last_pgm) if save_last_pgm else None
        self.last_pixels = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)
        if self.save_path and self.last_pixels:
            save_pgm(self.save_path, *self.last_pixels)

    def _run(self) -> None:
        import zmq

        ctx = zmq.Context()
        sock = ctx.socket(zmq.PULL)
        sock.setsockopt(zmq.RCVHWM, 8)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, 100)
        try:
            sock.connect(self.connect)
            while not self.stop_event.is_set():
                try:
                    parts = sock.recv_multipart(copy=False)
                except zmq.Again:
                    continue
                except zmq.ZMQError as exc:
                    self.errors += 1
                    self.last_error = str(exc)
                    break
                try:
                    frame = decode_parts(parts)
                except (ValueError, struct.error):
                    self.invalid += 1
                    continue
                self.received += 1
                if self.save_path:
                    self.last_pixels = (frame.width, frame.height, bytes(parts[1]))
                try:
                    self.queue.put_nowait(frame)
                except queue.Full:
                    self.queue_drops += 1
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.queue.put_nowait(frame)
                    except queue.Full:
                        self.queue_drops += 1
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
        finally:
            sock.close()
            ctx.term()
