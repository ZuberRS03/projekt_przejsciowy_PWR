"""Responder synchronizacji czasu ESP32 <-> RPi (specyfikacja §5.1-5.4, issue #12).

Odbiera SYNC_REQ (UDP 5001) i odpowiada SYNC_RESP z czasami t2 (odbiór) i t3 (wysyłka)
w ns zegara CLOCK_MONOTONIC. Bez logowania per pakiet; co jakiś czas jedna linia statystyk.
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from typing import Optional, Tuple

from protocol import (CLOCK_NAME, HEADER, MAGIC, TYPE_SYNC_REQ, TYPE_SYNC_RESP, VERSION,  # noqa: F401 (reeksport)
                      monotonic_ns)

SYNC_RESP = struct.Struct("<HBBIqqq")
DEFAULT_PORT = 5001


def parse_sync_req(data: bytes) -> Optional[Tuple[int, int]]:
    """Zwraca (seq, t1_us) albo None, gdy pakiet nie jest poprawnym SYNC_REQ."""
    if len(data) != HEADER.size:
        return None
    magic, version, msg_type, seq, t1_us = HEADER.unpack(data)
    if magic != MAGIC or version != VERSION or msg_type != TYPE_SYNC_REQ:
        return None
    return seq, t1_us


def build_sync_resp(seq: int, t1_us: int, t2_ns: int, t3_ns: int) -> bytes:
    return SYNC_RESP.pack(MAGIC, VERSION, TYPE_SYNC_RESP, seq, t3_ns, t1_us, t2_ns)


def serve(sock, clock=monotonic_ns, stats_interval=60.0, stop_event=None, log=print):
    """Pętla blokująca na związanym gnieździe UDP; kończy się po ustawieniu stop_event.

    Zwraca słownik z sumarycznymi statystykami (responses, dropped, send_errors).
    """
    sock.settimeout(min(1.0, stats_interval))
    buf = bytearray(SYNC_RESP.size)
    total = {"responses": 0, "dropped": 0, "send_errors": 0}
    clients = set()
    n = 0
    sum_us = 0.0
    max_us = 0.0
    last_stats = time.monotonic()

    while stop_event is None or not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(2048)  # większe niż MTU: za długie pakiety odrzuca parse_sync_req
        except socket.timeout:
            data = None
        except OSError:  # np. ConnectionResetError (ICMP) na Windows
            total["dropped"] += 1
            data = None
        if data is not None:
            t2 = clock()
            parsed = parse_sync_req(data)
            if parsed is None:
                total["dropped"] += 1
            else:
                # t3 tuż przed wysyłką: pack_into i sendto bez nic pomiędzy
                t3 = clock()
                SYNC_RESP.pack_into(buf, 0, MAGIC, VERSION, TYPE_SYNC_RESP, parsed[0], t3, parsed[1], t2)
                try:
                    sock.sendto(buf, addr)
                    total["responses"] += 1
                except OSError:
                    total["send_errors"] += 1
                clients.add(addr[0])
                n += 1
                d_us = (t3 - t2) / 1000
                sum_us += d_us
                max_us = max(max_us, d_us)
        now = time.monotonic()
        if now - last_stats >= stats_interval:
            log(f"[sync] odpowiedzi={total['responses']} odrzucone={total['dropped']} "
                f"bledy_wysylki={total['send_errors']} klienci={len(clients)} "
                f"t3-t2 max={max_us:.1f} us srednio={sum_us / n if n else 0.0:.1f} us "
                f"(okno {stats_interval:g} s)")
            clients.clear()
            n = 0
            sum_us = max_us = 0.0
            last_stats = now
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="adres nasłuchu")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port UDP")
    parser.add_argument("--stats-interval", type=float, default=60, help="okres statystyk [s]")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"[sync] nasluch na {args.host}:{args.port}, zegar: {CLOCK_NAME}", flush=True)
    try:
        serve(sock, stats_interval=args.stats_interval, log=lambda s: print(s, flush=True))
    except KeyboardInterrupt:
        print("[sync] zatrzymano", flush=True)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
