"""Wspólne stałe i układ wiadomości protokołu UDP/ZeroMQ (specyfikacja §5.2-5.4).

Little-endian, bez wyrównania (spakowane). Nagłówek wspólny ma 16 B.
"""

from __future__ import annotations

import struct
import time
from typing import NamedTuple, Optional

MAGIC = 0x5052  # "PR"
VERSION = 1

TYPE_IMU = 1
TYPE_SHOT = 2
TYPE_SYNC_REQ = 3
TYPE_SYNC_RESP = 4
TYPE_SYNC_REPORT = 5
TYPE_STATUS = 6
TYPE_VIDEO_FRAME = 16

FORMAT_Y8 = 1

if hasattr(time, "clock_gettime_ns") and hasattr(time, "CLOCK_MONOTONIC"):
    CLOCK_NAME = "CLOCK_MONOTONIC"

    def monotonic_ns() -> int:
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC)
else:  # Windows - tylko do testów
    CLOCK_NAME = "time.monotonic_ns"
    monotonic_ns = time.monotonic_ns

# magic, version, type, seq, t_send
HEADER = struct.Struct("<HBBIq")
# frame_seq, t_sensor_ns, exposure_us, frame_duration_us, line_time_ns, width, height, sensor_rows, format
VIDEO_META = struct.Struct("<IqIIIHHHB")
# część 1 wiadomości VIDEO_FRAME: nagłówek wspólny + metadane (47 B)
VIDEO_FRAME_HEADER = struct.Struct(HEADER.format + VIDEO_META.format[1:])


class VideoFrameHeader(NamedTuple):
    seq: int
    t_send_ns: int
    frame_seq: int
    t_sensor_ns: int
    exposure_us: int
    frame_duration_us: int
    line_time_ns: int
    width: int
    height: int
    sensor_rows: int
    format: int


def pack_video_header(seq, t_send_ns, frame_seq, t_sensor_ns, exposure_us, frame_duration_us,
                      line_time_ns, width, height, sensor_rows, fmt=FORMAT_Y8) -> bytes:
    return VIDEO_FRAME_HEADER.pack(MAGIC, VERSION, TYPE_VIDEO_FRAME, seq & 0xFFFFFFFF, t_send_ns,
                                   frame_seq & 0xFFFFFFFF, t_sensor_ns, exposure_us, frame_duration_us,
                                   line_time_ns, width, height, sensor_rows, fmt)


def parse_video_header(data: bytes) -> Optional[VideoFrameHeader]:
    """Zwraca VideoFrameHeader albo None, gdy część 1 nie jest poprawnym VIDEO_FRAME."""
    if len(data) != VIDEO_FRAME_HEADER.size:
        return None
    magic, version, msg_type, *fields = VIDEO_FRAME_HEADER.unpack(data)
    if magic != MAGIC or version != VERSION or msg_type != TYPE_VIDEO_FRAME:
        return None
    return VideoFrameHeader(*fields)
