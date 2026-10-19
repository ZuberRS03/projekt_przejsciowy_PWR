"""Test pracy kamery w docelowej konfiguracji (specyfikacja §7.2, wstęp do testu T4).

Uruchamia Camera Module 3 w trybie 1536x864 @ 120 fps ze stałą ekspozycją i wzmocnieniem,
odbiera klatki tak jak docelowy nadajnik (strumień lores 640x360, płaszczyzna Y) i mierzy:
rzeczywisty okres klatki z SensorTimestamp, zgubione klatki, opóźnienie odbioru,
obciążenie CPU, temperaturę i throttling. Bez wysyłki po sieci.
"""

import argparse
import csv
import statistics
import subprocess
import time

from picamera2 import Picamera2

SENSOR_SIZE = (1536, 864)
LORES_SIZE = (640, 360)
FRAME_US = 8333  # 120 fps


def cpu_times():
    with open("/proc/stat") as f:
        values = [int(v) for v in f.readline().split()[1:]]
    idle = values[3] + values[4]  # idle + iowait
    return sum(values), idle


def vcgencmd(*args):
    return subprocess.run(["vcgencmd", *args], capture_output=True, text=True).stdout.strip()


def percentile(sorted_values, p):
    return sorted_values[min(len(sorted_values) - 1, round(p / 100 * (len(sorted_values) - 1)))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--exposure-us", type=int, default=2000)
    parser.add_argument("--gain", type=float, default=4.0)
    parser.add_argument("--lens-position", type=float, default=0.5, help="dioptrie (1/m), 0 = nieskończoność")
    parser.add_argument("--csv", help="zapis surowych danych klatek")
    args = parser.parse_args()

    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": SENSOR_SIZE, "format": "YUV420"},
        lores={"size": LORES_SIZE, "format": "YUV420"},
        raw={"size": SENSOR_SIZE},
        buffer_count=6,
        controls={
            "FrameDurationLimits": (FRAME_US, FRAME_US),
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": args.exposure_us,
            "AnalogueGain": args.gain,
            "AfMode": 0,  # manual
            "LensPosition": args.lens_position,
        },
    )
    picam2.configure(config)
    print("Tryb sensora:", picam2.camera_configuration()["sensor"])
    picam2.start()

    # Rozbieg: pierwsze klatki po starcie mają jeszcze nieustalone parametry.
    for _ in range(30):
        picam2.capture_request().release()

    rows = []
    cpu_total0, cpu_idle0 = cpu_times()
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        request = picam2.capture_request()
        t_recv_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        md = request.get_metadata()
        y_plane = request.make_array("lores")[: LORES_SIZE[1]]  # Y8 jak w VIDEO_FRAME
        rows.append((md["SensorTimestamp"], t_recv_ns, md["FrameDuration"], md["ExposureTime"], int(y_plane[0, 0])))
        request.release()
    cpu_total1, cpu_idle1 = cpu_times()
    picam2.stop()
    picam2.close()

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["t_sensor_ns", "t_recv_ns", "frame_duration_us", "exposure_us", "pixel0"])
            writer.writerows(rows)

    periods_us = [(b[0] - a[0]) / 1000 for a, b in zip(rows, rows[1:])]
    dropped = sum(max(0, round(p / FRAME_US) - 1) for p in periods_us)
    latency_ms = sorted((r[1] - r[0]) / 1e6 for r in rows)
    span_s = (rows[-1][0] - rows[0][0]) / 1e9
    cpu_pct = 100 * (1 - (cpu_idle1 - cpu_idle0) / (cpu_total1 - cpu_total0))

    print(f"Klatki odebrane:       {len(rows)} w {span_s:.2f} s")
    print(f"FPS (SensorTimestamp): {(len(rows) - 1) / span_s:.2f}")
    print(f"FrameDuration (meta):  {statistics.median(r[2] for r in rows)} us, ExposureTime: {rows[-1][3]} us")
    print(f"Okres klatki [us]:     min {min(periods_us):.0f}, mediana {statistics.median(periods_us):.0f}, "
          f"max {max(periods_us):.0f}, odch. std {statistics.pstdev(periods_us):.1f}")
    print(f"Zgubione klatki:       {dropped} ({100 * dropped / (len(rows) + dropped):.2f}%)")
    print(f"Opóźnienie odbioru:    p50 {percentile(latency_ms, 50):.2f} ms, p95 {percentile(latency_ms, 95):.2f} ms, "
          f"max {latency_ms[-1]:.2f} ms")
    print(f"CPU (cały system):     {cpu_pct:.1f}%")
    print(f"Temperatura:           {vcgencmd('measure_temp')}")
    print(f"Throttling:            {vcgencmd('get_throttled')}")


if __name__ == "__main__":
    main()
