"""Korelacja zdarzen SHOT, probek IMU i VIDEO_FRAME w zegarze RPi (#16).

Nie analizujemy pikseli obrazu. Uzywamy czasu referencyjnego klatki dla jej
srodkowego wiersza, bez stalej C (kalibracja wizyjna bedzie osobnym etapem).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional
import time


@dataclass(frozen=True)
class FrameInfo:
    seq: int
    frame_seq: int
    t_sensor_ns: int
    exposure_us: int
    frame_duration_us: int
    line_time_ns: int
    width: int
    height: int
    sensor_rows: int

    def t_center_ns(self, calibration_ns: int = 0) -> int:
        """Model §6.2: y=height/2, zatem y_sensor=sensor_rows/2."""
        return round(self.t_sensor_ns + self.sensor_rows / 2 * self.line_time_ns
                     + self.exposure_us * 500 + calibration_ns)


@dataclass(frozen=True)
class ImuInfo:
    t_esp_us: int
    t_rpi_ns: int
    acc: tuple[int, int, int]
    gyro: tuple[int, int, int]


@dataclass(frozen=True)
class SyncQuality:
    selected: int
    min_rtt_us: float
    drift_ppm: float
    rms_residual_us: float


@dataclass(frozen=True)
class ShotInfo:
    session: int
    shot_id: int
    t_esp_us: int
    t_rpi_ns: Optional[int]
    quality: Optional[SyncQuality]


@dataclass(frozen=True)
class MatchResult:
    shot: ShotInfo
    status: str
    frame: Optional[FrameInfo] = None
    frame_t_ns: Optional[int] = None
    delta_ns: Optional[int] = None
    imu: Optional[ImuInfo] = None
    imu_delta_ns: Optional[int] = None


class Correlator:
    """Bufory metadanych i watermark; wywolywany tylko z watku glownego.

    Bufor klatek jest indeksowany czasem RPi; wideo moze nadejsc przed lub po
    SHOT. Warunek watermark jest dokladnie z §6.3 specyfikacji:
    najnowszy SensorTimestamp > T_shot + okres klatki.
    """

    def __init__(self, *, frame_history_s: float = 4.0,
                 max_delta_ms: float = 25.0, max_pending_s: float = 5.0,
                 calibration_ns: int = 0,
                 on_result: Callable[[MatchResult], None] | None = None):
        self.frame_history_ns = round(frame_history_s * 1e9)
        self.imu_history_ns = max(self.frame_history_ns, 4_000_000_000)
        self.max_delta_ns = round(max_delta_ms * 1e6)
        self.max_pending_ns = round(max_pending_s * 1e9)
        self.calibration_ns = calibration_ns
        self.on_result = on_result or (lambda _: None)
        self.frames: Deque[FrameInfo] = deque()
        self.imu: Deque[ImuInfo] = deque()
        self.pending: Deque[tuple[ShotInfo, int]] = deque()
        self.results = 0
        self.matched = 0
        self.unsynced = 0
        self.unresolved = 0
        self.total_frames = 0
        self.missing_frames = 0
        self.missing_video_seq = 0
        self.out_of_order_frames = 0
        self.frame_restarts = 0
        self.last_frame_seq: int | None = None
        self.last_video_seq: int | None = None
        self.last_sensor_ns: int | None = None

    def _emit(self, result: MatchResult) -> None:
        self.results += 1
        if result.status == 'MATCH':
            self.matched += 1
        elif result.status == 'UNSYNCED':
            self.unsynced += 1
        else:
            self.unresolved += 1
        self.on_result(result)

    def reset_esp_session(self) -> None:
        """Po restarcie ESP old pending nie wolno dopasowac do nowej epoki."""
        while self.pending:
            shot, _ = self.pending.popleft()
            self._emit(MatchResult(shot, 'ESP_RESTART'))
        self.imu.clear()
        # klatki RPi sa w tej samej, nieprzerwanej domenie czasu

    @staticmethod
    def _gap(current: int, previous: int) -> int | None:
        d = (current - previous) & 0xFFFFFFFF
        return None if d == 0 or d >= 0x80000000 else d - 1

    def add_frame(self, frame: FrameInfo) -> bool:
        if self.last_sensor_ns is not None and frame.t_sensor_ns <= self.last_sensor_ns:
            # Timestamp skoczyl wstecz: restart wysylki lub dane stare / nie w kolejnosci
            if frame.t_sensor_ns < self.last_sensor_ns - 1_000_000_000:
                self.frames.clear()
                self.last_frame_seq = None
                self.last_video_seq = None
                self.last_sensor_ns = None
                self.frame_restarts += 1
            else:
                self.out_of_order_frames += 1
                return False
        # Nadajnik video_sender moze zostac zrestartowany niezaleznie od RPi.
        # CLOCK_MONOTONIC wtedy nadal rosnie, ale obydwa liczniki zaczynaja od 0.
        if (self.last_frame_seq is not None and self.last_video_seq is not None
                and frame.seq < 5 and frame.frame_seq < 5
                and self.last_video_seq > 10 and self.last_frame_seq > 10
                and frame.seq < self.last_video_seq and frame.frame_seq < self.last_frame_seq
                and self.last_video_seq < 0xFFFF0000):
            self.frames.clear()
            self.last_frame_seq = None
            self.last_video_seq = None
            self.frame_restarts += 1
        if self.last_frame_seq is not None:
            gap = self._gap(frame.frame_seq, self.last_frame_seq)
            if gap is None:
                self.out_of_order_frames += 1
                return False
            self.missing_frames += gap
        if self.last_video_seq is not None:
            gap = self._gap(frame.seq, self.last_video_seq)
            if gap is not None:
                self.missing_video_seq += gap
        self.last_sensor_ns = frame.t_sensor_ns
        self.last_frame_seq = frame.frame_seq
        self.last_video_seq = frame.seq
        self.frames.append(frame)
        self.total_frames += 1
        while self.frames and frame.t_sensor_ns - self.frames[0].t_sensor_ns > self.frame_history_ns:
            self.frames.popleft()
        self._finalize_ready()
        return True

    def add_imu(self, sample: ImuInfo) -> None:
        if self.imu and sample.t_rpi_ns <= self.imu[-1].t_rpi_ns:
            return
        self.imu.append(sample)
        while self.imu and sample.t_rpi_ns - self.imu[0].t_rpi_ns > self.imu_history_ns:
            self.imu.popleft()

    def add_shot(self, shot: ShotInfo, now_ns: int | None = None) -> None:
        if shot.t_rpi_ns is None:
            self._emit(MatchResult(shot, 'UNSYNCED'))
            return
        self.pending.append((shot, time.monotonic_ns() if now_ns is None else now_ns))
        self._finalize_ready()

    def _finalize_ready(self) -> None:
        if not self.frames:
            return
        latest = self.frames[-1]
        # Moze byc wiele strzalow oczekujacych jednoczesnie
        remaining: Deque[tuple[ShotInfo, int]] = deque()
        while self.pending:
            shot, start_ns = self.pending.popleft()
            assert shot.t_rpi_ns is not None
            watermark_ns = shot.t_rpi_ns + latest.frame_duration_us * 1000
            if latest.t_sensor_ns > watermark_ns:
                self._resolve(shot)
            else:
                remaining.append((shot, start_ns))
        self.pending = remaining

    def _resolve(self, shot: ShotInfo) -> None:
        assert shot.t_rpi_ns is not None
        if not self.frames:
            self._emit(MatchResult(shot, 'NO_VIDEO'))
            return
        frame = min(self.frames,
                    key=lambda f: abs(f.t_center_ns(self.calibration_ns) - shot.t_rpi_ns))
        frame_t_ns = frame.t_center_ns(self.calibration_ns)
        delta_ns = frame_t_ns - shot.t_rpi_ns
        if abs(delta_ns) > self.max_delta_ns:
            self._emit(MatchResult(shot, 'NO_NEAR_FRAME', frame=frame,
                                   frame_t_ns=frame_t_ns, delta_ns=delta_ns))
            return
        nearest_imu = None
        imu_delta = None
        if self.imu:
            candidate = min(self.imu, key=lambda x: abs(x.t_rpi_ns - shot.t_rpi_ns))
            if abs(candidate.t_rpi_ns - shot.t_rpi_ns) <= 20_000_000:
                nearest_imu = candidate
                imu_delta = candidate.t_rpi_ns - shot.t_rpi_ns
        self._emit(MatchResult(shot, 'MATCH', frame, frame_t_ns, delta_ns,
                               nearest_imu, imu_delta))

    def expire(self, now_ns: int | None = None) -> None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        remaining: Deque[tuple[ShotInfo, int]] = deque()
        while self.pending:
            shot, queued_at = self.pending.popleft()
            if now - queued_at > self.max_pending_ns:
                self._emit(MatchResult(shot, 'VIDEO_TIMEOUT'))
            else:
                remaining.append((shot, queued_at))
        self.pending = remaining

    def finish(self) -> None:
        while self.pending:
            shot, _ = self.pending.popleft()
            self._emit(MatchResult(shot, 'END_WITHOUT_FRAME'))
