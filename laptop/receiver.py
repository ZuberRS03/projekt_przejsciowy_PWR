"""Odbiornik laptopa UDP 5000 + model synchronizacji ESP32 <-> RPi (#14).

Uruchomienie z katalogu repozytorium: python laptop/receiver.py
Bez zewnetrznych zaleznosci, Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import socket
import struct
import time

from clock_sync import ClockSynchronizer

MAGIC = 0x5052
VERSION = 1
TYPE_IMU = 1
TYPE_SHOT = 2
TYPE_SYNC_REPORT = 5
TYPE_STATUS = 6

HEADER = struct.Struct('<HBBIq')
IMU_META = struct.Struct('<BBH')
IMU_SAMPLE = struct.Struct('<qhhhhhh')
SHOT = struct.Struct('<IqB3x')
STATUS = struct.Struct('<HbBI')
SYNC_REPORT = struct.Struct('<qqqq')

CSV_FIELDS = [
    'session', 't1_us', 't2_ns', 't3_ns', 't4_us', 'esp_mid_us',
    'rpi_mid_us', 'rtt_us', 'selected', 'ready', 'n_selected',
    'n_window', 'a', 'b_us', 'drift_ppm', 'rms_residual_us'
]


class Receiver:
    def __init__(self, csv_path: str | None = None) -> None:
        self.sync = ClockSynchronizer()
        self.session = 1
        self.last_seq: int | None = None
        self.last_esp_send_us: int | None = None
        self.seen_shots: set[int] = set()
        self.received = 0
        self.missing_seq = 0
        self.invalid = 0
        self.out_of_order = 0
        self.sync_reports = 0
        self.unique_shots = 0
        self.duplicate_shots = 0
        self.window_packets = 0
        self.window_samples = 0
        self.window_sync = 0
        self.last_imu: tuple | None = None
        self.last_imu_arrived_at: float | None = None
        self.last_print = time.monotonic()
        self.csv_file = None
        self.csv_writer = None

        if csv_path:
            path = Path(csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.csv_file = path.open('w', newline='', encoding='utf-8')
            self.csv_writer = csv.DictWriter(self.csv_file, CSV_FIELDS)
            self.csv_writer.writeheader()

    def close(self) -> None:
        if self.csv_file is not None:
            self.csv_file.close()

    def _handle_header(self, seq: int, t_send_us: int) -> bool:
        """Jedna numeracja tylko pakietow ESP->laptop, jak w firmware #13."""
        if (self.last_esp_send_us is not None and
                t_send_us < self.last_esp_send_us - 1_000_000):
            if (self.last_seq is not None and seq < self.last_seq and
                    (self.last_seq - seq > 32 or
                     t_send_us < self.last_esp_send_us / 2)):
                self.session += 1
                self.sync.reset()
                self.seen_shots.clear()
                self.last_imu = None
                self.last_imu_arrived_at = None
                self.last_seq = None
                print(f'[RESTART] Nowa epoka zegara ESP32; sesja={self.session}. '
                      'Model synchronizacji wyzerowany.')
            else:
                # Stary, opozniony pakiet z poprzedniej sesji / poza kolejnoscia.
                self.out_of_order += 1
                return False

        if self.last_seq is not None:
            delta = (seq - self.last_seq) & 0xFFFFFFFF
            if delta == 0:
                self.out_of_order += 1
                return False
            if delta >= 0x80000000:
                self.out_of_order += 1
                return False
            if delta > 1:
                missing = delta - 1
                self.missing_seq += missing
                print(f'[WARN] Brak numerow sekwencji: +{missing}')

        self.last_seq = seq
        self.last_esp_send_us = t_send_us
        self.sync.expire(t_send_us)
        return True

    def accept_packet(self, packet: bytes) -> None:
        if len(packet) < HEADER.size:
            raise ValueError('Pakiet krotszy od naglowka')
        magic, version, kind, seq, t_send = HEADER.unpack_from(packet)
        if magic != MAGIC or version != VERSION:
            raise ValueError('Nieznany protokol lub wersja')
        # Nie wprowadzamy danych ze starej epoki do modelu.
        if not self._handle_header(seq, t_send):
            return

        payload = packet[HEADER.size:]
        if kind == TYPE_IMU:
            self._handle_imu(payload)
        elif kind == TYPE_SHOT:
            self._handle_shot(payload)
        elif kind == TYPE_STATUS:
            self._handle_status(payload)
        elif kind == TYPE_SYNC_REPORT:
            self._handle_sync(payload)
        else:
            raise ValueError(f'Nieznany typ pakietu: {kind}')

        self.received += 1
        self.window_packets += 1

    def _handle_imu(self, payload: bytes) -> None:
        if len(payload) < IMU_META.size:
            raise ValueError('IMU: brak metadanych')
        count, _sensor_range, _reserved = IMU_META.unpack_from(payload)
        expected = IMU_META.size + count * IMU_SAMPLE.size
        if not (1 <= count <= 64) or len(payload) != expected:
            raise ValueError('IMU: nieprawidlowa dlugosc')
        offset = IMU_META.size + (count - 1) * IMU_SAMPLE.size
        self.last_imu = IMU_SAMPLE.unpack_from(payload, offset)
        self.last_imu_arrived_at = time.monotonic()
        self.window_samples += count

    def _handle_shot(self, payload: bytes) -> None:
        if len(payload) != SHOT.size:
            raise ValueError('SHOT: nieprawidlowa dlugosc')
        shot_id, shot_t_us, repeat = SHOT.unpack(payload)
        if shot_id in self.seen_shots:
            self.duplicate_shots += 1
            return
        self.seen_shots.add(shot_id)
        self.unique_shots += 1
        converted = self.sync.to_rpi_ns(shot_t_us)
        if converted is None:
            print(f'[SHOT] id={shot_id} t_ESP={shot_t_us} us '
                  f'(UNSYNCED, repeat={repeat})')
        else:
            print(f'[SHOT] id={shot_id} t_ESP={shot_t_us} us '
                  f't_RPi={converted} ns (repeat={repeat})')

    def _handle_status(self, payload: bytes) -> None:
        if len(payload) != STATUS.size:
            raise ValueError('STATUS: nieprawidlowa dlugosc')
        _battery, rssi, flags, overruns = STATUS.unpack(payload)
        # Bez spamowania: raportujemy w podsumowaniu raz na sekunde.
        self.last_status = (rssi, bool(flags & 1), overruns)

    def _handle_sync(self, payload: bytes) -> None:
        if len(payload) != SYNC_REPORT.size:
            raise ValueError('SYNC_REPORT: nieprawidlowa dlugosc')
        t1, t2, t3, t4 = SYNC_REPORT.unpack(payload)
        if not self.sync.add_report(t1, t2, t3, t4):
            raise ValueError('SYNC_REPORT: nieprawidlowe lub przeterminowane timestampy')
        self.sync_reports += 1
        self.window_sync += 1

        if self.csv_writer is not None:
            p = self.sync.last_point
            fit = self.sync.fit
            assert p is not None
            self.csv_writer.writerow({
                'session': self.session,
                't1_us': t1, 't2_ns': t2, 't3_ns': t3, 't4_us': t4,
                'esp_mid_us': p.esp_mid_us,
                'rpi_mid_us': p.rpi_mid_us,
                'rtt_us': round(p.rtt_us, 3),
                'selected': int(p in self.sync.selected_points),
                'ready': int(self.sync.ready),
                'n_selected': len(self.sync.selected_points),
                'n_window': len(self.sync.points),
                'a': f'{fit.a:.12f}' if fit else '',
                'b_us': f'{fit.b_us:.3f}' if fit else '',
                'drift_ppm': f'{fit.drift_ppm:.3f}' if fit else '',
                'rms_residual_us': f'{fit.rms_residual_us:.3f}' if fit else '',
            })
            self.csv_file.flush()

    def print_status(self) -> None:
        now = time.monotonic()
        if now - self.last_print < 1.0:
            return
        print(f'[RECEIVER] pkts/s={self.window_packets} '
              f'IMU samples/s={self.window_samples} SYNC/s={self.window_sync} '
              f'missing_seq={self.missing_seq} invalid={self.invalid} '
              f'out_of_order={self.out_of_order}')

        fit = self.sync.fit
        if fit:
            print(f'[SYNC] READY | window={fit.samples_window} '
                  f'filtered={fit.samples_used} | '
                  f'minRTT={fit.min_rtt_us / 1e3:.3f} ms | '
                  f'a={fit.a:.10f} drift={fit.drift_ppm:+.2f} ppm | '
                  f'b={fit.b_us:.1f} us | '
                  f'RMS residual={fit.rms_residual_us:.1f} us')
        else:
            print(f'[SYNC] WAITING | '
                  f'window={len(self.sync.points)} '
                  f'filtered={len(self.sync.selected_points)}/{self.sync.min_filtered}')

        if self.last_imu is not None and self.last_imu_arrived_at is not None:
            if now - self.last_imu_arrived_at < 1.5:
                t, ax, ay, az, gx, gy, gz = self.last_imu
                t_rpi = self.sync.to_rpi_ns(t)
                print(f'[IMU] t_ESP={t} us '
                      f't_RPi={str(t_rpi) + " ns" if t_rpi is not None else "UNSYNCED"} '
                      f'ACC=({ax},{ay},{az}) GYRO=({gx},{gy},{gz})')
            else:
                print('[IMU] Brak nowych probek (nie wyswietlam starej wartosci)')

        status = getattr(self, 'last_status', None)
        if status is not None:
            rssi, online, overruns = status
            print(f'[ESP] RSSI={rssi} dBm WiFi={online} '
                  f'imu_overruns_total={overruns}')

        self.window_packets = 0
        self.window_samples = 0
        self.window_sync = 0
        self.last_print = now


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--csv', default=None,
                        help='Opcjonalny zapis raportow SYNC do CSV, np. logs/sync.csv')
    args = parser.parse_args()

    receiver = Receiver(csv_path=args.csv)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
        sock.settimeout(0.2)
        print(f'[OK] UDP receiver listening on {args.host}:{args.port}')
        print('SYNC: model t_rpi = a*t_esp + b | okno 60 s, filtr RTT_min+1ms')
        print('CTRL+C konczy test\n')
        try:
            while True:
                try:
                    data, _addr = sock.recvfrom(2048)
                    try:
                        receiver.accept_packet(data)
                    except ValueError as error:
                        receiver.invalid += 1
                        print(f'[INVALID] {error}')
                except socket.timeout:
                    pass
                receiver.print_status()
        except KeyboardInterrupt:
            print('\n=== KONIEC TESTU ===')
            print(f'Pakiety={receiver.received} SYNC={receiver.sync_reports} '
                  f'SHOT={receiver.unique_shots} duplikaty_SHOT={receiver.duplicate_shots}')
            print(f'Brakujace_seq={receiver.missing_seq} invalid={receiver.invalid} '
                  f'restarty={receiver.sync.restarts}')
    finally:
        sock.close()
        receiver.close()


if __name__ == '__main__':
    main()
