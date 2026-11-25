"""Synchronizacja domen czasu ESP32 -> Raspberry Pi (specyfikacja §4.3).

Nie wymaga pakietow zewnetrznych. Wejscie: cztery timestampy z SYNC_REPORT.
ESP32: mikrosekundy; RPi: nanosekundy. Model wewnetrznie operuje
na mikrosekundach, ale funkcja to_rpi_ns() zwraca nanosekundy RPi.

UWAGA: rozrzut reszt regresji nie jest pomiarem absolutnego bledu synchronizacji.
Dokladnosc trzeba zweryfikowac niezaleznym testem T1.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Deque, Optional

WINDOW_US = 60_000_000.0
RTT_SLACK_US = 1_000.0
MIN_FILTERED = 10


@dataclass(frozen=True)
class SyncPoint:
    esp_mid_us: float
    rpi_mid_us: float
    rtt_us: float


@dataclass(frozen=True)
class ClockFit:
    """Wyznaczony model liniowy y=a*x+b, z stabilnymi numerycznie kotwicami."""

    a: float
    b_us: float
    ref_esp_us: float
    ref_rpi_us: float
    samples_used: int
    samples_window: int
    min_rtt_us: float
    rms_residual_us: float
    span_s: float

    @property
    def drift_ppm(self) -> float:
        return (self.a - 1.0) * 1_000_000.0

    def to_rpi_us(self, t_esp_us: float) -> float:
        # Nie mnozymy duzych wartosci czasu, aby ograniczyc blad zaokraglenia.
        return self.ref_rpi_us + self.a * (t_esp_us - self.ref_esp_us)

    def to_rpi_ns(self, t_esp_us: float) -> int:
        return round(self.to_rpi_us(t_esp_us) * 1_000.0)


class ClockSynchronizer:
    def __init__(self, window_us: float = WINDOW_US,
                 rtt_slack_us: float = RTT_SLACK_US,
                 min_filtered: int = MIN_FILTERED) -> None:
        self.window_us = window_us
        self.rtt_slack_us = rtt_slack_us
        self.min_filtered = min_filtered
        self.points: Deque[SyncPoint] = deque()
        self.fit: Optional[ClockFit] = None
        self.accepted_reports = 0
        self.rejected_reports = 0
        self.restarts = 0
        self.last_point: Optional[SyncPoint] = None
        self.selected_points: tuple[SyncPoint, ...] = ()

    @property
    def ready(self) -> bool:
        return self.fit is not None

    def reset(self) -> None:
        """Wywolaj po wykryciu restartu ESP32 (nowa epoka esp_timer)."""
        self.points.clear()
        self.fit = None
        self.last_point = None
        self.selected_points = ()
        self.restarts += 1

    def add_report(self, t1_us: int, t2_ns: int,
                   t3_ns: int, t4_us: int) -> bool:
        """Dodaje prawidlowy raport, zwraca False dla blednych timestampow."""
        if t4_us < t1_us or t3_ns < t2_ns or t1_us < 0 or t2_ns < 0:
            self.rejected_reports += 1
            return False

        # Stosujemy roznice calkowitoliczbowe PRZED konwersja na float.
        # Ogranicza to ryzyko utraty precyzji dla duzych czasow RPi.
        server_us = (t3_ns - t2_ns) / 1_000.0
        rtt_us = (t4_us - t1_us) - server_us
        if rtt_us < 0 or not isfinite(rtt_us):
            self.rejected_reports += 1
            return False

        x = t1_us + (t4_us - t1_us) / 2.0
        y = (t2_ns / 1_000.0) + (t3_ns - t2_ns) / 2_000.0
        point = SyncPoint(x, y, rtt_us)

        # Reorder UDP: starszy SYNC_REPORT nie powinien cofac okna.
        if self.points and x <= self.points[-1].esp_mid_us:
            self.rejected_reports += 1
            return False

        self.points.append(point)
        self.last_point = point
        self.accepted_reports += 1
        self._prune_and_fit(reference_esp_us=x)
        return True

    def expire(self, now_esp_us: int) -> None:
        """Wygasza stare dane także wtedy, gdy SYNC_REPORT przestaly docierac.

        Wywolywac przy innych pakietach ESP32, z ich header.t_send.
        """
        if self.points and now_esp_us > self.points[-1].esp_mid_us:
            self._prune_and_fit(reference_esp_us=float(now_esp_us))

    def _prune_and_fit(self, reference_esp_us: float) -> None:
        while self.points and reference_esp_us - self.points[0].esp_mid_us > self.window_us:
            self.points.popleft()

        if not self.points:
            self.selected_points = ()
            self.fit = None
            return

        rtt_min = min(p.rtt_us for p in self.points)
        selected = tuple(
            p for p in self.points if p.rtt_us <= rtt_min + self.rtt_slack_us
        )
        self.selected_points = selected
        if len(selected) < self.min_filtered:
            self.fit = None
            return

        # Regresja centrowana: poprawna dla duzych, roznych epok zegarow.
        n = len(selected)
        mx = sum(p.esp_mid_us for p in selected) / n
        my = sum(p.rpi_mid_us for p in selected) / n
        den = sum((p.esp_mid_us - mx) ** 2 for p in selected)
        if den <= 0:
            self.fit = None
            return
        a = sum((p.esp_mid_us - mx) * (p.rpi_mid_us - my) for p in selected) / den
        if not isfinite(a) or a <= 0:
            self.fit = None
            return
        b = my - a * mx
        residuals = [(p.rpi_mid_us - my) - a * (p.esp_mid_us - mx)
                     for p in selected]
        rms = sqrt(sum(r * r for r in residuals) / n)

        self.fit = ClockFit(
            a=a,
            b_us=b,
            ref_esp_us=mx,
            ref_rpi_us=my,
            samples_used=n,
            samples_window=len(self.points),
            min_rtt_us=rtt_min,
            rms_residual_us=rms,
            span_s=(selected[-1].esp_mid_us - selected[0].esp_mid_us) / 1e6,
        )

    def to_rpi_ns(self, t_esp_us: int) -> Optional[int]:
        if self.fit is None:
            return None
        return self.fit.to_rpi_ns(t_esp_us)
