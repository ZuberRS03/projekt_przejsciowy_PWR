"""Task #16: UDP 5000 (ESP32) + ZeroMQ PULL 5555 (RPi) + korelacja SHOT/VIDEO_FRAME.

Uruchamiaj z katalogu repozytorium:
  python laptop/integrated_receiver.py --sync-csv laptop/logs/sync.csv --matches-csv laptop/logs/matches.csv
Wymaga pyzmq: python -m pip install pyzmq
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import queue
import socket
import time

from correlation import Correlator, ImuInfo, MatchResult, ShotInfo, SyncQuality
from receiver import Receiver, IMU_META, IMU_SAMPLE, SHOT
from video_stream import VideoPump

MATCH_FIELDS = [
    'session', 'shot_id', 'status', 't_shot_esp_us', 't_shot_rpi_ns',
    'frame_seq', 't_frame_center_ns', 'delta_frame_minus_shot_ns',
    'abs_delta_ms', 'imu_t_esp_us', 'imu_t_rpi_ns', 'imu_delta_ms',
    'sync_filtered', 'sync_min_rtt_ms', 'sync_drift_ppm', 'sync_rms_residual_us',
]


class MatchLogger:
    def __init__(self, path: str | None):
        self.file = None
        self.writer = None
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self.file = p.open('w', newline='', encoding='utf-8')
            self.writer = csv.DictWriter(self.file, MATCH_FIELDS)
            self.writer.writeheader()

    def __call__(self, result: MatchResult):
        s, f, q, i = result.shot, result.frame, result.shot.quality, result.imu
        data = {
            'session': s.session, 'shot_id': s.shot_id, 'status': result.status,
            't_shot_esp_us': s.t_esp_us, 't_shot_rpi_ns': s.t_rpi_ns or '',
            'frame_seq': f.frame_seq if f else '',
            't_frame_center_ns': result.frame_t_ns if result.frame_t_ns is not None else '',
            'delta_frame_minus_shot_ns': result.delta_ns if result.delta_ns is not None else '',
            'abs_delta_ms': f'{abs(result.delta_ns)/1e6:.3f}' if result.delta_ns is not None else '',
            'imu_t_esp_us': i.t_esp_us if i else '',
            'imu_t_rpi_ns': i.t_rpi_ns if i else '',
            'imu_delta_ms': f'{result.imu_delta_ns/1e6:+.3f}' if result.imu_delta_ns is not None else '',
            'sync_filtered': q.selected if q else '',
            'sync_min_rtt_ms': f'{q.min_rtt_us/1e3:.3f}' if q else '',
            'sync_drift_ppm': f'{q.drift_ppm:+.2f}' if q else '',
            'sync_rms_residual_us': f'{q.rms_residual_us:.1f}' if q else '',
        }
        if self.writer is not None:
            self.writer.writerow(data)
            self.file.flush()
        if result.status == 'MATCH':
            imu_str = (f'{result.imu_delta_ns/1e6:+.2f} ms'
                       if result.imu_delta_ns is not None else 'none')
            print(f'[MATCH] shot={s.shot_id} frame={f.frame_seq} '
                  f'delta(frame-shot)={result.delta_ns/1e6:+.3f} ms '
                  f'IMU={imu_str}', flush=True)
        else:
            print(f'[MATCH] shot={s.shot_id} status={result.status}', flush=True)

    def close(self):
        if self.file:
            self.file.close()


class IntegratedUdpReceiver(Receiver):
    """Wykorzystuje CALE dekodowanie i model z #14, dopina obsluge zdarzen #16."""
    def __init__(self, correlator: Correlator, csv_path: str | None = None):
        super().__init__(csv_path=csv_path)
        self.correlator = correlator

    def _handle_header(self, seq: int, t_send_us: int) -> bool:
        previous_session = self.session
        okay = super()._handle_header(seq, t_send_us)
        if self.session != previous_session:
            self.correlator.reset_esp_session()
        return okay

    def _handle_imu(self, payload: bytes) -> None:
        super()._handle_imu(payload)
        # Do dalszej korelacji zachowujemy WSZYSTKIE probki, nie tylko ostatnia.
        if not self.sync.ready:
            return
        count, _range, _reserved = IMU_META.unpack_from(payload)
        for idx in range(count):
            t_us, ax, ay, az, gx, gy, gz = IMU_SAMPLE.unpack_from(
                payload, IMU_META.size + idx * IMU_SAMPLE.size)
            t_ns = self.sync.to_rpi_ns(t_us)
            if t_ns is not None:
                self.correlator.add_imu(ImuInfo(t_us, t_ns, (ax, ay, az), (gx, gy, gz)))

    def _handle_shot(self, payload: bytes) -> None:
        before = self.unique_shots
        super()._handle_shot(payload)  # deduplikacja i wypisanie przez #14
        if self.unique_shots == before:
            return
        shot_id, shot_t_us, _repeat = SHOT.unpack(payload)
        fit = self.sync.fit
        quality = (SyncQuality(fit.samples_used, fit.min_rtt_us,
                               fit.drift_ppm, fit.rms_residual_us) if fit else None)
        shot_ns = self.sync.to_rpi_ns(shot_t_us)
        self.correlator.add_shot(ShotInfo(self.session, shot_id, shot_t_us,
                                          shot_ns, quality))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0', help='UDP bind (laptop)')
    parser.add_argument('--port', type=int, default=5000, help='ESP UDP port')
    parser.add_argument('--video', default='tcp://192.168.50.10:5555', help='ZeroMQ PULL connect do RPi')
    parser.add_argument('--sync-csv', default=None, help='CSV raportow SYNC (#14)')
    parser.add_argument('--matches-csv', default='laptop/logs/matches.csv',
                        help='CSV korelacji (puste pole --matches-csv "" wylacza zapis)')
    parser.add_argument('--save-last-pgm', default=None, help='Zapisz ostatni odebrany obraz Y8 jako PGM przy wyjsciu')
    parser.add_argument('--frame-history-s', type=float, default=4.0)
    parser.add_argument('--max-delta-ms', type=float, default=25.0)
    parser.add_argument('--max-wait-s', type=float, default=5.0)
    parser.add_argument('--calibration-ns', type=int, default=0,
                        help='C dla t_row w nanosekundach: 0 dopoki nie wykonamy T2')
    args = parser.parse_args()

    try:
        import zmq  # noqa:F401
    except ImportError as exc:
        raise SystemExit('Brak pyzmq. Zainstaluj: python -m pip install pyzmq') from exc

    matches = MatchLogger(args.matches_csv or None)
    correlation = Correlator(frame_history_s=args.frame_history_s,
                             max_delta_ms=args.max_delta_ms,
                             max_pending_s=args.max_wait_s,
                             calibration_ns=args.calibration_ns,
                             on_result=matches)
    udp = IntegratedUdpReceiver(correlation, csv_path=args.sync_csv)
    video = VideoPump(args.video, save_last_pgm=args.save_last_pgm)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.01)
    video.start()
    print(f'[START] UDP {args.host}:{args.port} | VIDEO PULL {args.video}', flush=True)
    print('[START] Korelacja w czasie CLOCK_MONOTONIC RPi; C=0, srodek obrazu; '
          'nie wykonujemy analizy pikseli.', flush=True)
    last_print = time.monotonic()
    last_frames = 0
    try:
        while True:
            try:
                packet, addr = sock.recvfrom(2048)
                try:
                    udp.accept_packet(packet)
                except ValueError as exc:
                    udp.invalid += 1
                    print(f'[INVALID UDP] {exc}')
            except socket.timeout:
                pass
            # Watek wideo przekazuje TYLKO metadane. ZeroMQ != blokujace UDP.
            for _ in range(256):
                try:
                    frame = video.queue.get_nowait()
                except queue.Empty:
                    break
                correlation.add_frame(frame)
            correlation.expire()
            udp.print_status()
            now = time.monotonic()
            if now - last_print >= 1.0:
                fps = (correlation.total_frames - last_frames) / (now - last_print)
                print(f'[VIDEO] frames/s={fps:.1f} total={correlation.total_frames} '
                      f'missing_frame_seq={correlation.missing_frames} '
                      f'missing_header_seq={correlation.missing_video_seq} '
                      f'video_restarts={correlation.frame_restarts} '
                      f'queue_drops={video.queue_drops} invalid={video.invalid} '
                      f'out_of_order={correlation.out_of_order_frames} '
                      f'pending_shots={len(correlation.pending)} '
                      f'matches={correlation.matched}', flush=True)
                if video.errors:
                    print(f'[VIDEO] Worker error: {video.last_error}', flush=True)
                last_frames = correlation.total_frames
                last_print = now
    except KeyboardInterrupt:
        print('\n=== KONIEC TESTU #16 ===')
    finally:
        sock.close()
        video.stop()
        correlation.finish()
        udp.close()
        matches.close()
        print(f'[SUMMARY] UDP={udp.received} shots={udp.unique_shots} '
              f'frames={correlation.total_frames} matched={correlation.matched} '
              f'unsynced={correlation.unsynced} unresolved={correlation.unresolved} '
              f'frame_loss={correlation.missing_frames} '
              f'video_queue_drops={video.queue_drops} invalid_video={video.invalid}')


if __name__ == '__main__':
    main()
