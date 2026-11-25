
import socket
import struct
import time

HOST = "0.0.0.0"
PORT = 5000

MAGIC = 0x5052
VERSION = 1

TYPE_IMU = 1
TYPE_SHOT = 2
TYPE_SYNC_REPORT = 5
TYPE_STATUS = 6

HEADER = struct.Struct("<HBBIq")
IMU_META = struct.Struct("<BBH")
IMU_SAMPLE = struct.Struct("<qhhhhhh")
SHOT = struct.Struct("<IqB3x")
STATUS = struct.Struct("<HbBI")
SYNC_REPORT = struct.Struct("<qqqq")

last_seq = None
last_timestamp = None

seen_shots = set()

total_packets = 0
total_imu_samples = 0
missing_packets = 0
duplicate_shots = 0
unique_shots = 0
invalid_packets = 0
sync_reports = 0
invalid_sync_reports = 0

window_packets = 0
window_samples = 0

last_sample = None
last_status = time.monotonic()


def track_sequence(seq, t_send):
    global last_seq, last_timestamp, missing_packets

    if last_seq is not None:
        # Wykrycie prawdopodobnego restartu ESP32
        if (
            last_timestamp is not None
            and t_send < last_timestamp - 1_000_000
        ):
            print("[INFO] Wykryto restart ESP32")
            last_seq = None
            seen_shots.clear()

    if last_seq is not None:
        delta = (seq - last_seq) & 0xFFFFFFFF

        if 1 < delta < 0x80000000:
            lost = delta - 1
            missing_packets += lost
            print(f"[WARN] Brak {lost} pakietow UDP")

        elif delta == 0:
            print(f"[WARN] Zduplikowany seq={seq}")

        elif delta >= 0x80000000:
            print(f"[WARN] Pakiet poza kolejnoscia: {seq}")

        if 0 < delta < 0x80000000:
            last_seq = seq
            last_timestamp = t_send
    else:
        last_seq = seq
        last_timestamp = t_send


def handle_imu(payload):
    global total_imu_samples
    global window_samples, last_sample

    if len(payload) < IMU_META.size:
        raise ValueError("IMU: za krotkie metadane")

    count, sensor_range, reserved = IMU_META.unpack_from(
        payload, 0
    )

    expected = IMU_META.size + count * IMU_SAMPLE.size

    if not 1 <= count <= 64 or len(payload) != expected:
        raise ValueError("IMU: niepoprawna dlugosc")

    for i in range(count):
        offset = IMU_META.size + i * IMU_SAMPLE.size
        sample = IMU_SAMPLE.unpack_from(payload, offset)
        last_sample = sample

    total_imu_samples += count
    window_samples += count


def handle_shot(payload):
    global unique_shots, duplicate_shots

    if len(payload) != SHOT.size:
        raise ValueError("SHOT: niepoprawna dlugosc")

    shot_id, t_shot_us, repeat = SHOT.unpack(payload)

    if shot_id in seen_shots:
        duplicate_shots += 1
        print(
            f"[SHOT DUPLICATE] id={shot_id}, repeat={repeat}"
        )
        return

    seen_shots.add(shot_id)
    unique_shots += 1

    print(
        f"[SHOT] id={shot_id}, "
        f"t={t_shot_us} us, repeat={repeat}"
    )


def handle_sync_report(payload):
    global sync_reports, invalid_sync_reports

    if len(payload) != SYNC_REPORT.size:
        raise ValueError("SYNC_REPORT: niepoprawna dlugosc")

    t1_us, t2_ns, t3_ns, t4_us = SYNC_REPORT.unpack(payload)

    if t4_us < t1_us or t3_ns < t2_ns:
        invalid_sync_reports += 1
        raise ValueError("SYNC_REPORT: niepoprawna kolejnosc znacznikow")

    # t1,t4 w us; t2,t3 w ns. Zachowujemy surowe znaczniki.
    rtt_us = (t4_us - t1_us) - (t3_ns - t2_ns) / 1000.0
    sync_reports += 1

    print(
        f"[SYNC_REPORT] #{sync_reports} "
        f"RTT={rtt_us / 1000.0:.3f} ms | "
        f"t1={t1_us}us t2={t2_ns}ns "
        f"t3={t3_ns}ns t4={t4_us}us"
    )


def handle_status(payload):
    if len(payload) != STATUS.size:
        raise ValueError("STATUS: niepoprawna dlugosc")

    battery, rssi, flags, overruns = STATUS.unpack(payload)

    print(
        f"[ESP STATUS] RSSI={rssi} dBm | "
        f"IMU overruns={overruns} | "
        f"WiFi flag={bool(flags & 1)}"
    )

    # battery=0 oznacza, ze pomiar nie jest aktywny


def main():
    global total_packets, window_packets
    global invalid_packets, last_status
    global window_samples

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    sock.settimeout(0.25)

    print(f"[OK] UDP receiver listening on {HOST}:{PORT}")
    print("CTRL+C aby zakonczyc\n")

    try:
        while True:
            try:
                data, address = sock.recvfrom(2048)

                if len(data) < HEADER.size:
                    raise ValueError("Za krotki naglowek")

                magic, version, msg_type, seq, t_send = (
                    HEADER.unpack_from(data)
                )

                if magic != MAGIC or version != VERSION:
                    raise ValueError("Nieznany protokol")

                track_sequence(seq, t_send)

                total_packets += 1
                window_packets += 1

                payload = data[HEADER.size:]

                if msg_type == TYPE_IMU:
                    handle_imu(payload)

                elif msg_type == TYPE_SHOT:
                    handle_shot(payload)

                elif msg_type == TYPE_STATUS:
                    handle_status(payload)

                elif msg_type == TYPE_SYNC_REPORT:
                    handle_sync_report(payload)

                else:
                    print(f"[WARN] Nieznany typ: {msg_type}")

            except socket.timeout:
                pass

            except ValueError as error:
                invalid_packets += 1
                print(f"[ERROR] {error}")

            now = time.monotonic()

            if now - last_status >= 1.0:
                print(
                    f"[RECEIVER] pakiety/s={window_packets} | "
                    f"probki/s={window_samples} | "
                    f"braki seq={missing_packets} | "
                    f"invalid={invalid_packets}"
                )

                if last_sample is not None:
                    t, ax, ay, az, gx, gy, gz = last_sample

                    print(
                        f"  IMU t={t} us | "
                        f"ACC=({ax},{ay},{az}) | "
                        f"GYRO=({gx},{gy},{gz})"
                    )

                window_packets = 0
                window_samples = 0
                last_status = now

    except KeyboardInterrupt:
        print("\n=== WYNIKI SESJI ===")
        print(f"Pakiety odebrane: {total_packets}")
        print(f"Probki IMU: {total_imu_samples}")
        print(f"Brakujace seq: {missing_packets}")
        print(f"Unikalne zdarzenia SHOT: {unique_shots}")
        print(f"Duplikaty SHOT: {duplicate_shots}")
        print(f"Niepoprawne pakiety: {invalid_packets}")
        print(f"Odebrane SYNC_REPORT: {sync_reports}")

    finally:
        sock.close()


if __name__ == "__main__":
    main()
