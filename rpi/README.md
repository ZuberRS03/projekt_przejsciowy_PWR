# Raspberry Pi — konfiguracja i test kamery

Dotyczy zadań [#6 Konfiguracja RaspberryPi](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/6)
i [#12 Implementacja serwera synchronizacji czasu na Raspberry Pi](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/12).
Docelowa konfiguracja: [specyfikacja §7.2](../docs/specyfikacja.md#72-raspberry-pi-4b).

## Stan urządzenia

| Element | Wartość |
|---------|---------|
| Sprzęt | Raspberry Pi 4 Model B Rev 1.4, 8 GB |
| System | Raspberry Pi OS Lite 64-bit (Debian 13 trixie), jądro 6.18 |
| Host / użytkownik | `mgr-zuber` / `admin` |
| Kamera | Camera Module 3 (IMX708) na złączu CSI, wykrywana automatycznie (`camera_auto_detect=1`) |
| Pakiety | `python3-picamera2` 0.3.38, `libcamera` 0.7.2, `rpicam-apps-lite` 1.14 (apt) |
| Python | 3.13 systemowy + `uv` 0.13 (`~/.local/bin/uv`) |
| Sieć | `eth0` 192.168.50.10 (router `mgr_zuber`, bez internetu); `wlan0` — inna sieć z dostępem do internetu |

`eth0` jest podłączone do wydzielonego routera (192.168.50.10 z DHCP routera); stałe IP oraz wyłączenie WiFi i BT —
do zrobienia. Pi nie ma internetu przez `eth0` ani `git`, więc kod wdrażamy przez `scp`.

## Konfiguracja

### Kamera

Weryfikacja wykrycia i trybów sensora:

```sh
rpicam-hello --list-cameras
# 0 : imx708 [4608x2592 10-bit RGGB]
#     Modes: 'SRGGB10_CSI2P' : 1536x864 [120.13 fps - (768, 432)/3072x1728 crop]
```

### Governor CPU `performance`

Domyślny governor `ondemand` przy małym obciążeniu trzyma niski zegar CPU — pętla odbioru
klatek nie nadąża i kolejka buforów się zapełnia (zmierzone: 1,1% zgubionych klatek,
opóźnienie rośnie do ~50 ms). Pakiet `raspberrypi-sys-mods` ustawia `ondemand` regułą udev,
która nadpisuje też parametr jądra `cpufreq.default_governor`, dlatego nadpisujemy tę regułę:

```sh
echo 'KERNEL=="cpu*", SUBSYSTEM=="cpu", ATTR{cpufreq/scaling_governor}="performance"' \
  | sudo tee /etc/udev/rules.d/60-ondemand-governor.rules
sudo reboot
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor   # performance ×4
```

### Środowisko Pythona (uv)

`picamera2` i `libcamera` są dostępne tylko z apt, więc środowisko uv musi widzieć pakiety
systemowe:

```sh
cd ~/projekt/rpi
~/.local/bin/uv venv --system-site-packages --python /usr/bin/python3
~/.local/bin/uv run camera_check.py --seconds 60
```

## Podgląd na żywo

Do ustawienia kamery i ostrości: docelowy tryb sensora i 120 fps, ale skompresowany H.264
(ok. 6–10 Mbit/s, działa po WiFi). Nie jest to docelowy tor (bez kompresji, §5.4).

Na Pi (czeka na połączenie; kończy się po zamknięciu odtwarzacza):

```sh
rpicam-vid -t 0 -n --mode 1536:864:10:P --width 640 --height 360 --framerate 120 \
  --autofocus-mode continuous \
  --codec h264 --bitrate 10000000 --inline --listen -o tcp://0.0.0.0:8888
```

Na laptopie (ffplay z FFmpeg):

```powershell
ffplay -fflags nobuffer -flags low_delay -framedrop -probesize 32 -analyzeduration 0 -framerate 120 -vf setpts=0 -f h264 tcp://mgr-zuber:8888
```

- `-framerate 120` — surowy H.264 nie ma znaczników czasu, a ffplay domyślnie zakłada 25 fps,
  przez co opóźnienie rośnie bez końca.
- `-vf setpts=0` — wyświetlanie klatek od razu po zdekodowaniu; bez tego zaległość z bufora
  na starcie zostaje na stałe (ok. 1 s opóźnienia).
- `--autofocus-mode continuous` i automatyczna ekspozycja dają zwykły podgląd. Ustawienia
  docelowe (jak w `camera_check.py`): `--shutter 2000 --gain 4 --awb daylight --saturation 0
  --autofocus-mode manual --lens-position 0.5` — obraz jest wtedy ciemny, żeby odcinała się
  kropka lasera. `--lens-position` w dioptriach (1/odległość w m).
- Kamera obsługuje jeden proces naraz — podglądu nie da się uruchomić razem z `camera_check.py`.

## Test kamery — `camera_check.py`

Uruchamia kamerę w docelowej konfiguracji (1536×864 @ 120 fps, stała ekspozycja 2 ms
i wzmocnienie 4, ręczna ostrość, strumień `lores` 640×360 Y8), odbiera klatki bez wysyłki po sieci
i mierzy: rzeczywisty okres klatki z `SensorTimestamp`, zgubione klatki, opóźnienie odbioru
(`CLOCK_MONOTONIC` − `SensorTimestamp`), CPU, temperaturę i throttling.
Opcja `--csv` zapisuje surowe dane klatek.

### Wyniki (2026-10-18, bez radiatora, governor `performance`)

| Parametr | 60 s | 300 s |
|----------|------|-------|
| Klatki | 7208 | 36 034 |
| FPS | 120,13 | 120,11 |
| Okres klatki (mediana / odch. std) | 8325 µs / 1,2 µs | 8325 µs / 10,2 µs |
| Zgubione klatki | 0 | 0 |
| Opóźnienie odbioru p50 / p95 / max | 14,1 / 15,6 / 16,9 ms | 14,1 / 15,6 / 22,1 ms |
| CPU (cały system) | 8,6% | 8,6% |
| Temperatura na końcu | 43,8 °C | 50,1 °C |
| `get_throttled` | `0x0` | `0x0` |

Dla porównania z governorem `ondemand` (20 s): 119,7 fps, 0,33% zgubionych klatek,
opóźnienie p95 43 ms.

Wnioski:

- Kamera stabilnie utrzymuje 120 fps — warunek dokładności W2 po stronie kamery jest spełniony.
- Odbiór w Pythonie zajmuje < 10% CPU, więc zostaje duży zapas na wysyłkę ZeroMQ (test T4).
- Opóźnienie ~14 ms (ok. 1,7 klatki) to opóźnienie potoku libcamera/ISP; nie wpływa na
  dokładność, bo czas klatki pochodzi z `SensorTimestamp`.

## Responder synchronizacji czasu — `sync_responder.py`

Odpowiada na `SYNC_REQ` z ESP32 (UDP 5001) i zwraca `SYNC_RESP` z czasami t2 i t3 zegara
RPi. Protokół i algorytm: [specyfikacja §5.4](../docs/specyfikacja.md#54-wiadomości-rpi),
[§4](../docs/specyfikacja.md#4-domeny-zegarowe-i-synchronizacja). Tylko biblioteka standardowa
— działa na `/usr/bin/python3`, bez środowiska uv.

- Argumenty: `--host` (domyślnie `0.0.0.0`), `--port` (5001), `--stats-interval` (60 s).
- Niepoprawne pakiety (długość, `magic`, wersja, typ) są odrzucane bez odpowiedzi.
- Bez logów per pakiet; co `--stats-interval` jedna linia statystyk do journald.
- Klient testowy `sync_client.py` emuluje ESP32 i mierzy RTT oraz czas obsługi t3−t2.

### Protokół

Wszystkie pola little-endian. Nagłówek wspólny (16 B) jest taki sam w obu wiadomościach.

| Offset | Pole | Typ | `SYNC_REQ` (16 B, typ 3) | `SYNC_RESP` (32 B, typ 4) |
|--------|------|-----|--------------------------|---------------------------|
| 0 | `magic` | u16 | `0x5052` | `0x5052` |
| 2 | `version` | u8 | 1 | 1 |
| 3 | `type` | u8 | 3 | 4 |
| 4 | `seq` | u32 | numer żądania | skopiowany z żądania |
| 8 | `t_send` | i64 | t1 ESP32 [µs] | t3 RPi [ns] |
| 16 | `t1_us` | i64 | — | echo `t_send` z żądania |
| 24 | `t2_ns` | i64 | — | t2 RPi [ns] |

- t2 — `CLOCK_MONOTONIC` tuż po powrocie z `recvfrom`, przed walidacją pakietu.
- t3 — `CLOCK_MONOTONIC` tuż przed `sendto` (pakowanie odpowiedzi i wysyłka bez nic pomiędzy).

### Wdrożenie na Pi (scp)

Pi nie ma `git` ani internetu przez `eth0`, więc pliki kopiujemy z laptopa. Jednorazowo
warto skonfigurować logowanie kluczem SSH (klucz publiczny w `~/.ssh/authorized_keys` na Pi),
żeby `ssh`/`scp` nie pytały o hasło.

Z katalogu głównego repozytorium na laptopie (PowerShell):

```powershell
ssh admin@192.168.50.10 "mkdir -p ~/projekt/rpi/tests ~/projekt/rpi/systemd"
scp rpi/sync_responder.py rpi/sync_client.py admin@192.168.50.10:~/projekt/rpi/
scp rpi/tests/__init__.py rpi/tests/test_sync_responder.py admin@192.168.50.10:~/projekt/rpi/tests/
scp rpi/systemd/sync-responder.service admin@192.168.50.10:~/projekt/rpi/systemd/
```

Na Pi — instalacja usługi (start przy każdym uruchomieniu, restart po awarii):

```sh
sudo cp ~/projekt/rpi/systemd/sync-responder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sync-responder
```

Jednostka: `User=admin`, `Restart=on-failure` (`RestartSec=2`), `Nice=-10`, start po
`network-online.target`, `ExecStart=/usr/bin/python3 -u /home/admin/projekt/rpi/sync_responder.py`.

Aktualizacja:

- po zmianie kodu — skopiować pliki ponownie (`scp`) i `sudo systemctl restart sync-responder`,
- po zmianie jednostki — `scp`, potem `sudo cp ...` jak wyżej, `sudo systemctl daemon-reload`
  i `sudo systemctl restart sync-responder`.

### Diagnostyka

```sh
systemctl status sync-responder
journalctl -u sync-responder -f
ss -ulpn | grep 5001
```

Linia statystyk (co 60 s, okno = `--stats-interval`):

```
[sync] odpowiedzi=1200 odrzucone=0 bledy_wysylki=0 klienci=1 t3-t2 max=85.0 us srednio=40.2 us (okno 60 s)
```

Liczniki `odpowiedzi`, `odrzucone` i `bledy_wysylki` są narastające od startu; `klienci`
(liczba adresów IP w oknie), `t3-t2` i `srednio` dotyczą ostatniego okna. Wartości w
przykładzie są ilustracyjne.

### Testy

| Test | Gdzie | Komenda | Co sprawdza |
|------|-------|---------|-------------|
| Testy jednostkowe | laptop (katalog główny repo) | `python -m unittest discover -s rpi/tests -v` | parsowanie i budowa pakietów, odrzucanie niepoprawnych, pętla `serve` |
| Testy jednostkowe | Pi (`~/projekt/rpi`) | `python3 -m unittest discover -s tests -v` | to samo na docelowym Pythonie 3.13 |
| Loopback | Pi (`~/projekt/rpi`) | `python3 sync_client.py --host 127.0.0.1 --count 1000 --interval 0.01` | brak strat; RTT i t3−t2 bez sieci |
| Sieć | laptop | `python rpi/sync_client.py --host 192.168.50.10 --count 300 --interval 0.1` | RTT p50/p95/max na torze laptop (WiFi) → router → Pi (`eth0`), jak z ESP32; brak strat |
| Niepoprawne pakiety | laptop | `python rpi/sync_client.py --host 192.168.50.10 --malformed --count 20` | responder odrzuca śmieci i dalej odpowiada |
| Restart po awarii | Pi | `sudo systemctl kill -s KILL sync-responder`, potem `systemctl is-active sync-responder` | `Restart=on-failure` — po ok. 2 s `active` |
| Autostart | Pi | `sudo reboot`, potem `systemctl is-active sync-responder` | usługa startuje po restarcie systemu |

- Z laptopa używać `--host 192.168.50.10`: na Windows nazwa `mgr-zuber` może przez mDNS
  wskazać link-local IPv6 interfejsu `wlan0` zamiast `eth0`.
- Klient wypisuje: wysłane / odebrane / timeouty / niepoprawne / spóźnione, RTT p50/p95/max/min
  [µs], t3−t2 serwera p50/p95/max [µs] i `WYNIK: OK/BLAD`; kod wyjścia 0/1.

### Wyniki (2026-11-23)

Wyniki zostaną uzupełnione po testach na Pi.
