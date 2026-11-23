"""Klient diagnostyczny synchronizacji czasu - emuluje ESP32 (SYNC_REQ -> SYNC_RESP).

Mierzy RTT i czas przetwarzania po stronie serwera, sprawdza poprawność odpowiedzi.
Z --malformed wysyła też błędne pakiety, na które serwer nie może odpowiedzieć.
"""

import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_responder import (DEFAULT_PORT, HEADER, MAGIC, SYNC_RESP, TYPE_SYNC_REQ,  # noqa: E402
                            TYPE_SYNC_RESP, VERSION)


def percentile(sorted_values, p):
    if not sorted_values:
        return float("nan")
    return sorted_values[min(len(sorted_values) - 1, round(p / 100 * (len(sorted_values) - 1)))]


def now_us():
    # perf_counter_ns: QPC na Windows (monotonic_ns ma tam ~15 ms rozdzielczości);
    # t1/t4 muszą być spójne tylko w obrębie klienta
    return time.perf_counter_ns() // 1000


def malformed_packets():
    good = HEADER.pack(MAGIC, VERSION, TYPE_SYNC_REQ, 0, 0)
    return {
        "zly magic": HEADER.pack(0x1234, VERSION, TYPE_SYNC_REQ, 0, 0),
        "zla wersja": HEADER.pack(MAGIC, VERSION + 1, TYPE_SYNC_REQ, 0, 0),
        "zly typ": HEADER.pack(MAGIC, VERSION, TYPE_SYNC_RESP, 0, 0),
        "zla dlugosc (15 B)": good[:-1],
        "zla dlugosc (17 B)": good + b"\x00",
    }


def recv_reply(sock, deadline):
    """Zwraca datagram albo None po przekroczeniu deadline (czas time.monotonic)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    sock.settimeout(remaining)
    try:
        return sock.recv(256)
    except (socket.timeout, ConnectionResetError):
        return None


def check_malformed(sock, timeout):
    """Zwraca liczbę błędnych pakietów, na które mimo to przyszła odpowiedź."""
    replies = 0
    for name, pkt in malformed_packets().items():
        sock.send(pkt)
        if recv_reply(sock, time.monotonic() + min(timeout, 0.2)) is not None:
            print(f"BLAD: odpowiedz na pakiet: {name}")
            replies += 1
    return replies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="mgr-zuber", help="adres responderu")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--count", type=int, default=100, help="liczba zapytań")
    parser.add_argument("--interval", type=float, default=0.1, help="odstęp między zapytaniami [s]")
    parser.add_argument("--timeout", type=float, default=0.5, help="czas oczekiwania na odpowiedź [s]")
    parser.add_argument("--malformed", action="store_true",
                        help="wyślij też błędne pakiety (serwer ma je zignorować)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect((args.host, args.port))

    bad_replies = check_malformed(sock, args.timeout) if args.malformed else 0
    received = timeouts = invalid = stale = 0
    rtts, procs = [], []

    for i in range(args.count):
        t1_us = now_us()
        sock.send(HEADER.pack(MAGIC, VERSION, TYPE_SYNC_REQ, i, t1_us))
        deadline = time.monotonic() + args.timeout
        while True:
            data = recv_reply(sock, deadline)
            t4_us = now_us()
            if data is None:
                timeouts += 1
                break
            if len(data) != SYNC_RESP.size:
                invalid += 1
                break
            magic, version, msg_type, seq, t3, r_t1, t2 = SYNC_RESP.unpack(data)
            if seq < i:
                stale += 1  # spóźniona odpowiedź na wcześniejsze zapytanie
                continue
            if (magic != MAGIC or version != VERSION or msg_type != TYPE_SYNC_RESP
                    or seq != i or r_t1 != t1_us or t2 > t3):
                invalid += 1
                break
            received += 1
            procs.append((t3 - t2) / 1000)
            rtts.append((t4_us - t1_us) - (t3 - t2) / 1000)
            break
        time.sleep(args.interval)

    if args.malformed:
        print(f"Błędne pakiety: odpowiedzi={bad_replies} (oczekiwano 0)")

    rtts.sort()
    procs.sort()
    nan = float("nan")
    print(f"Wysłano: {args.count}  odebrano: {received}  timeouty (straty): {timeouts}  "
          f"niepoprawne odpowiedzi: {invalid}  spóźnione: {stale}")
    print(f"RTT [us]: p50={percentile(rtts, 50):.0f} p95={percentile(rtts, 95):.0f} "
          f"max={rtts[-1] if rtts else nan:.0f} min={rtts[0] if rtts else nan:.0f}")
    print(f"Serwer t3-t2 [us]: p50={percentile(procs, 50):.1f} p95={percentile(procs, 95):.1f} "
          f"max={procs[-1] if procs else nan:.1f}")

    ok = invalid == 0 and bad_replies == 0 and timeouts <= 0.01 * args.count
    print("WYNIK:", "OK" if ok else "BLAD")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
