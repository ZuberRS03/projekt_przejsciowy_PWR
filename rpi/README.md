# Raspberry Pi — konfiguracja i test kamery

Dotyczy zadań [#6 Konfiguracja RaspberryPi](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/6)
[#12 Implementacja serwera synchronizacji czasu na Raspberry Pi](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/12)
i [#15 Implementacja transmisji klatek kamery z Raspberry Pi](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/15).
Docelowa konfiguracja: [specyfikacja §7.2](../docs/specyfikacja.md#72-raspberry-pi-4b).

## Stan urządzenia

| Element | Wartość |
|---------|---------|
| Sprzęt | Raspberry Pi 4 Model B Rev 1.4, 8 GB |
| System | Raspberry Pi OS Lite 64-bit (Debian 13 trixie), jądro 6.18 |
| Host / użytkownik | `mgr-zuber` / `admin` |
| Kamera | Camera Module 3 (IMX708) na złączu CSI, wykrywana automatycznie (`camera_auto_detect=1`) |
| Pakiety | `python3-picamera2` 0.3.38, `libcamera` 0.7.2, `rpicam-apps-lite` 1.14 (apt), `python3-zmq` 26.4 (z pliku `.deb`, bez internetu — [instalacja](#instalacja-pyzmq-bez-internetu-na-pi)) |
| Python | 3.13 systemowy + `uv` 0.13 (`~/.local/bin/uv`) |
| Sieć | `eth0` 192.168.50.10 (router `mgr_zuber`, bez internetu); `wlan0` — inna sieć z dostępem do internetu |

`eth0` jest podłączone do wydzielonego routera (192.168.50.10 z DHCP routera); stałe IP oraz wyłączenie WiFi i BT —
do zrobienia. Pi nie ma internetu przez `eth0` ani `git`, więc kod wdrażamy przez `scp` ([wdrożenie](#wdrożenie-na-pi-scp)).

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

## Wdrożenie na Pi (scp)

Pi nie ma `git` ani internetu przez `eth0`, więc pliki kopiujemy z laptopa. Jednorazowo
warto skonfigurować logowanie kluczem SSH (klucz publiczny w `~/.ssh/authorized_keys` na Pi),
żeby `ssh`/`scp` nie pytały o hasło. Przed pierwszym `scp` trzeba też zaakceptować klucz
hosta Pi pod adresem IP: jedno interaktywne `ssh admin@192.168.50.10` (klucz zaakceptowany
wcześniej tylko pod nazwą `mgr-zuber` nie wystarczy — z `BatchMode` `scp` kończy się błędem
„Host key verification failed”).

Z katalogu głównego repozytorium na laptopie (PowerShell); poniższe polecenia kopiują
wszystkie pliki z `rpi/` (moduły: [responder](#responder-synchronizacji-czasu--sync_responderpy),
[nadajnik wideo](#nadajnik-wideo--video_senderpy)):

```powershell
ssh admin@192.168.50.10 "mkdir -p ~/projekt/rpi/tests ~/projekt/rpi/systemd"
scp rpi/protocol.py rpi/camera_config.py rpi/camera_check.py rpi/sync_responder.py rpi/sync_client.py rpi/video_sender.py rpi/video_receiver.py admin@192.168.50.10:~/projekt/rpi/
scp rpi/tests/__init__.py rpi/tests/test_sync_responder.py rpi/tests/test_video.py admin@192.168.50.10:~/projekt/rpi/tests/
scp rpi/systemd/sync-responder.service rpi/systemd/video-sender.service admin@192.168.50.10:~/projekt/rpi/systemd/
```

Usługi systemd instaluje się osobno, w opisie danego modułu. Aktualizacja po zmianie kodu:
skopiować pliki ponownie (`scp`) i zrestartować usługę (`sudo systemctl restart <usługa>`).

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

Na Pi — instalacja usługi (start przy każdym uruchomieniu, restart po awarii):

```sh
sudo cp ~/projekt/rpi/systemd/sync-responder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sync-responder
```

Jednostka: `User=admin`, `Restart=on-failure` (`RestartSec=2`), `Nice=-10`, start po
`network-online.target`, `ExecStart=/usr/bin/python3 -u /home/admin/projekt/rpi/sync_responder.py`.

Aktualizacja (pliki kopiuje się według [wdrożenia](#wdrożenie-na-pi-scp)):

- po zmianie kodu — `scp` i `sudo systemctl restart sync-responder`,
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

Zegar systemowy (czas ścienny) Pi nie jest synchronizowany — Pi nie ma RTC ani internetu
przez `eth0` (NTP nie działa), więc daty w `journalctl` mogą być nieaktualne. Nie wpływa to
na synchronizację, która używa `CLOCK_MONOTONIC`.

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

Pi 4B na `eth0` (192.168.50.10), laptop testowy po WiFi (192.168.50.165) przez router
`mgr_zuber` (wiersze „PC (Ethernet)” — PC po kablu); governor `performance`, `get_throttled` = `0x0`;
usługa systemd (`Nice=-10`).

| Test | Wymiany (odebrane/wysłane) | RTT p50 / p95 / max | t3−t2 p50 / p95 / max | Wynik |
|------|----------------------------|---------------------|-----------------------|-------|
| Loopback na Pi (127.0.0.1, 1000 × co 10 ms) | 1000/1000 | 54 / 60 / 251 µs | 2,7 / 3,1 / 23,5 µs | OK |
| Sieć laptop (WiFi) → Pi (`eth0`) (300 × co 100 ms) | 298/300 (2 timeouty, 0,67%) | 5,1 / 15,7 / 64,5 ms (min 1,6 ms) | 2,9 / 5,7 / 37,9 µs | OK |
| Niepoprawne pakiety (5 rodzajów) + 20 wymian | 20/20, 0 odpowiedzi na błędne | 5,1 / 11,8 / 17,6 ms | 3,0 / 3,4 / 7,8 µs | OK |
| Sieć PC (Ethernet) → Pi (`eth0`) (300 × co 100 ms) | 300/300 (0 timeoutów) | 0,39 / 0,47 / 0,98 ms (min 0,30 ms) | 2,9 / 4,9 / 15,2 µs | OK |
| Niepoprawne pakiety + 20 wymian, PC (Ethernet) | 20/20, 0 odpowiedzi na błędne | p50 0,40 ms | — | OK |

- Testy jednostkowe: 6/6 OK na laptopie (Python 3.10) i na Pi (Python 3.13).
- Restart po `SIGKILL`: usługa wróciła po ok. 2 s (`NRestarts=1`).
- Autostart po restarcie Pi (`sudo reboot`): usługa `active` ok. 22,5 s od startu jądra, bez
  restartów; 50/50 wymian z laptopa OK (RTT p50 5,2 ms, t3−t2 p50 3,4 µs).

Wnioski:

- Czas obsługi po stronie RPi (t3−t2) to pojedyncze µs (max < 40 µs) — pomijalny wobec
  budżetu synchronizacji ≤ 1 ms (spec §2).
- Zmienność RTT i straty pochodzą z toru WiFi (laptop), nie z respondera — dlatego algorytm
  z §4.3 filtruje próbki `RTT ≤ RTT_min + 1 ms`.
- Powtórzenie z PC po kablu (Ethernet 1 Gbit do routera `mgr_zuber`): RTT jest ok. 13× niższe
  niż po WiFi (p50 0,39 ms wobec 5,1 ms) i bez strat — wcześniejsze RTT pochodziło z łącza WiFi
  PC, nie z respondera.
- Responder ignoruje niepoprawne pakiety i działa dalej.
- Wynik dla właściwego toru ESP32 → RPi zostanie zmierzony w #13.

## Nadajnik wideo — `video_sender.py`

Wysyła klatki kamery do laptopa jako `VIDEO_FRAME` przez ZeroMQ PUSH (tcp 5555), bez
kompresji, z metadanymi czasu (`SensorTimestamp`). Protokół, wybór PUSH/PULL i budżet
przepustowości: [specyfikacja §5.4](../docs/specyfikacja.md#54-wiadomości-rpi), przeliczanie
czasu klatki: [§6.2](../docs/specyfikacja.md#62-czas-klatki-i-korekta-rolling-shutter).
Wymaga `python3-picamera2` i `pyzmq` — działa na `/usr/bin/python3` (jak responder, bez uv).

- Wątek główny odbiera klatki z kamery (`lores` 640×360), kopiuje płaszczyznę Y raz i oddaje
  ją do ograniczonej kolejki (`--queue-size`, domyślnie 4; przy przepełnieniu odrzucana jest
  najstarsza klatka). Osobny wątek wysyła klatki przez ZeroMQ (`SNDHWM` 2, `SNDTIMEO` 10 ms).
- Gdy nikt nie odbiera, klatki starsze niż `--max-age-ms` (50) albo wyprzedzone przez nowsze
  w kolejce są porzucane (`stale_drops`) — odbiorca, który dołączy później, dostaje od razu
  świeże klatki, bez sztucznej luki w `frame_seq`.
- Argumenty: `--bind` (`tcp://*:5555`), `--exposure-us` (2000), `--gain` (4), `--lens-position`
  (0,5 dpt; wartości domyślne z `camera_config.py`, wspólne z `camera_check.py`), `--queue-size` (4),
  `--sndhwm` (2), `--max-age-ms` (50), `--stats-interval` (60 s), `--seconds` (0 = do zatrzymania),
  `--fake` (syntetyczne klatki 120 fps bez kamery — testy na laptopie).
- `SIGTERM` i Ctrl+C kończą pracę łagodnie. Bez logów per klatka; co `--stats-interval`
  jedna linia statystyk.
- Odbiornik diagnostyczny `video_receiver.py` (laptop) waliduje każdą wiadomość i liczy straty,
  FPS i przepustowość. Wspólny układ nagłówka i typy: `protocol.py`; konfiguracja kamery:
  `camera_config.py` (używana też przez `camera_check.py`).

### Format VIDEO_FRAME

Wiadomość dwuczęściowa (multipart), little-endian, bez wyrównania. Część 1 ma 47 B:
nagłówek wspólny (16 B, typ 16) + metadane.

| Offset | Pole | Typ | Wartość |
|--------|------|-----|---------|
| 0 | `magic` | u16 | `0x5052` |
| 2 | `version` | u8 | 1 |
| 3 | `type` | u8 | 16 |
| 4 | `seq` | u32 | numer wysłanej wiadomości |
| 8 | `t_send` | i64 | `CLOCK_MONOTONIC` tuż przed wysyłką [ns] |
| 16 | `frame_seq` | u32 | numer klatki wyliczany z `SensorTimestamp` |
| 20 | `t_sensor_ns` | i64 | `SensorTimestamp` [ns] |
| 28 | `exposure_us` | u32 | `ExposureTime` |
| 32 | `frame_duration_us` | u32 | `FrameDuration` (8325 µs) |
| 36 | `line_time_ns` | u32 | 9209 ns |
| 40 | `width` | u16 | 640 |
| 42 | `height` | u16 | 360 |
| 44 | `sensor_rows` | u16 | 864 |
| 46 | `format` | u8 | 1 = Y8 |

Część 2: płaszczyzna Y, 640 × 360 = 230 400 B.

- `frame_seq` a `seq`: libcamera nie podaje licznika klatek, więc `frame_seq` jest wyliczany
  z `SensorTimestamp`: 0 dla pierwszej klatki, potem `+= max(1, round(Δt / FrameDuration))`.
  Luka w `frame_seq` oznacza klatkę utraconą przed wysyłką (kamera lub kolejka). Nagłówkowe
  `seq` liczy wysłane wiadomości i jest ciągłe (TCP nie gubi wiadomości), więc luka w `seq`
  oznaczałaby błąd transportu.
- `line_time_ns` = (szerokość 1536 + hblank 3680) / pixel_rate 566,4 MHz = 9209 ns (kontrolki
  sensora IMX708; hblank jest tylko do odczytu). Sprawdzenie: 904 wiersze × 9,209 µs =
  8325 µs = `FrameDuration`.
- Płaszczyzna Y: `lores` jest skonfigurowany jako YUV420 (640×360, stride 640, bez dopełnienia);
  Y to pierwsze 360 wierszy bufora (230 400 B), które nadajnik kopiuje raz przez `MappedArray`.
- `SensorTimestamp` jest w domenie `CLOCK_MONOTONIC` — tej samej co `t2`/`t3` respondera
  synchronizacji (zmierzone: `CLOCK_MONOTONIC` − `SensorTimestamp` ≈ 14 ms to opóźnienie
  potoku; `BOOTTIME` − `MONOTONIC` = 2,8 µs). Dzięki temu laptop przelicza czas klatki
  tym samym offsetem co czas strzału.

### Instalacja pyzmq (bez internetu na Pi)

Pi nie ma internetu przez `eth0`, a tymczasowa trasa przez `wlan0` nie działa (DNS z routera
`mgr_zuber` nie rozwiązuje nazw), więc pakiet `python3-zmq` 26.4.0-1 (Debian trixie, arm64)
instalujemy z pliku `.deb` pobranego na laptopie. Brakowało tylko tego pakietu —
`libzmq5` 4.3.5 był już zainstalowany.

```sh
# laptop: pobranie i suma kontrolna
curl -O http://deb.debian.org/debian/pool/main/p/pyzmq/python3-zmq_26.4.0-1_arm64.deb
sha256sum python3-zmq_26.4.0-1_arm64.deb
# Pi: suma z podpisanego indeksu apt - musi być taka sama
apt-cache show python3-zmq | grep SHA256
# a236cabddceae93e25fcbdd9ad7c4ac2dc5c9e6a1807e6195406b3f1618ca9e4
```

```sh
scp python3-zmq_26.4.0-1_arm64.deb admin@192.168.50.10:/tmp/
# Pi
sudo apt install /tmp/python3-zmq_26.4.0-1_arm64.deb
python3 -c "import zmq; print(zmq.pyzmq_version())"   # 26.4.0
```

Na laptopie odbiornik potrzebuje `pyzmq` — najprościej przez `uv` (patrz niżej).

### Uruchomienie

Ręcznie na Pi (kamera obsługuje jeden proces naraz — wcześniej zatrzymać `camera_check.py`
i podgląd `rpicam-vid`):

```sh
cd ~/projekt/rpi
python3 video_sender.py
```

Jako usługa systemd — jednostka `video-sender.service` (`User=admin`, `Restart=on-failure`,
`RestartSec=2`, `Nice=-10`, start po `network-online.target`) jest zainstalowana w
`/etc/systemd/system/`, ale **nie jest włączona** do autostartu:

```sh
sudo cp ~/projekt/rpi/systemd/video-sender.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start video-sender      # start ręczny
sudo systemctl stop video-sender
journalctl -u video-sender -f
```

Autostart (`systemctl enable`) zostanie włączony przy integracji (#16): dopóki usługa działa,
kamera jest zajęta, więc nie da się uruchomić `camera_check.py` ani podglądu `rpicam-vid`.

Odbiornik na laptopie (katalog główny repozytorium; PowerShell):

```powershell
uv run --no-project --with pyzmq python rpi/video_receiver.py --connect tcp://192.168.50.10:5555 --seconds 30 --save-pgm klatka.pgm
```

- Argumenty: `--connect` (`tcp://192.168.50.10:5555`), `--seconds` (10, liczone od pierwszej
  klatki), `--timeout` (5 s maks. ciszy w strumieniu), `--save-pgm PATH` (ostatnia klatka
  jako PGM P5).
- Wynik: wiadomości (w tym błędne), poprawne klatki, luki `seq`, brakujące klatki (%),
  FPS z `t_sensor`, przepustowość, okres `t_sensor` i `WYNIK: OK/BLAD`. Kod wyjścia 0 = brak
  błędnych wiadomości, utracone klatki ≤ 0,5% (kryterium T3) i odebrano co najmniej jedną klatkę.
- Opóźnienia nadawcy odbiornik nie liczy (różne zegary Pi i laptopa).

### Diagnostyka

Linia statystyk (co 60 s, okno = `--stats-interval`):

```
[video] fps=120.12 wyslane=7208 camera_drops=0 queue_drops=0 stale_drops=0 przechwycenie p50/max=15.50/21.00 ms wysylka p50/max=0.14/0.60 ms (okno 60 s)
```

Liczniki `wyslane`, `camera_drops`, `queue_drops` i `stale_drops` są narastające od startu;
`fps` oraz czasy dotyczą ostatniego okna. Wartości w przykładzie są ilustracyjne.

- `fps` — z `SensorTimestamp` klatek w oknie.
- `wyslane` — liczba wysłanych wiadomości (= ostatnie `seq`).
- `camera_drops` — klatki utracone przez kamerę (luka w `frame_seq` między kolejnymi
  odebranymi klatkami).
- `queue_drops` — klatki odrzucone z pełnej kolejki (wysyłka nie nadąża).
- `stale_drops` — klatki porzucone, bo nikt nie odbierał (brak odbiorcy lub pełny `SNDHWM`)
  i były starsze niż `--max-age-ms` albo wyprzedzone nowszymi. Rosną przed połączeniem
  odbiornika i po jego zakończeniu; podczas stabilnej pracy powinny stać w miejscu.
- `przechwycenie` — `CLOCK_MONOTONIC` − `SensorTimestamp` z kopią klatki [ms].
- `wysylka` — czas `send_multipart` [ms].

### Testy

| Test | Gdzie | Komenda | Co sprawdza |
|------|-------|---------|-------------|
| Testy jednostkowe | laptop (katalog główny repo) | `uv run --no-project --with pyzmq python -m unittest discover -s rpi/tests -v` | nagłówek `VIDEO_FRAME`, licznik `frame_seq`, kolejka drop-oldest, statystyki odbiornika, test end-to-end na `127.0.0.1` (`--fake`), porzucanie klatek bez odbiorcy; bez `pyzmq` testy sieciowe są pomijane |
| Testy jednostkowe | Pi (`~/projekt/rpi`) | `python3 -m unittest discover -s tests -v` | to samo na docelowym Pythonie 3.13 i pyzmq 26.4 |
| V1 — loopback | Pi | `python3 video_sender.py --seconds 40 &` i `python3 video_receiver.py --connect tcp://127.0.0.1:5555 --seconds 30` | brak strat i obciążenie CPU bez sieci (nadajnik i odbiornik na jednym Pi) |
| V2 — Pi → PC | laptop/PC po Ethernecie | `uv run --no-project --with pyzmq python rpi/video_receiver.py --seconds 30 --save-pgm klatka.pgm` (nadajnik na Pi) | straty i przepustowość przez sieć; poprawność obrazu (PGM) |
| V3 — regresja kamery | Pi | `uv run camera_check.py --seconds 20` | refaktoryzacja `camera_config.py` nie zmieniła parametrów kamery |
| V4 — T4 (10 min) | Pi + PC | Pi: `python3 video_sender.py --seconds 625`; PC: `uv run --no-project --with pyzmq python rpi/video_receiver.py --seconds 600` | test T4 ze specyfikacji §8: fps, CPU, temperatura, `get_throttled` z wysyłką |

### Wyniki nadajnika (2026-11-23)

Pi 4B bez radiatora, governor `performance`; odbiornik: komputer stacjonarny deweloperski
(nie docelowy laptop) połączony Ethernetem 1 Gbit z routerem `mgr_zuber` (metryka interfejsu
Ethernet podniesiona, żeby internet zostawał na WiFi). Scena ciemna z założenia
(ekspozycja 2 ms, wzmocnienie 4).

| Parametr | V1 loopback na Pi (30 s) | V2 Pi → PC, Ethernet (30 s) | V3 `camera_check.py` (20 s) |
|----------|--------------------------|-----------------------------|-----------------------------|
| Klatki odebrane | 3610 | 3609 | 2403 |
| Brakujące / błędne | 0 (0,00%) / 0 | 0 / 0 | 0 zgubionych |
| Luki `seq` nagłówka | 0 | 0 | — |
| FPS | 120,12 | 120,12 | 120,12 |
| Przepustowość | 221,8 Mbit/s | 221,7 Mbit/s | — |
| Okres `t_sensor` p50 / max | 8,32 / 8,34 ms | 8,32 / 8,34 ms | mediana 8325 µs, odch. std 1,3 µs |
| Opóźnienie przechwycenia p50 / max | 15,5 / 21,0 ms | 15,5 / 18,9 ms | 14,12 / 16,95 ms (p95 15,65 ms) |
| Czas wysyłki p50 | 0,14 ms | 0,14 ms | — |
| CPU | nadajnik ok. 40–44% rdzenia, odbiornik ok. 9–10%, cały system 14% | — | 8,6% (cały system) |
| Temperatura na końcu | 57,9 °C (start 54,5 °C) | 56,9 °C | 56,9 °C |
| `get_throttled` | `0x0` | `0x0` | `0x0` |

V4 — test T4 ze specyfikacji §8 (10 min odbioru na PC po Ethernecie, nadajnik uruchomiony ręcznie,
pomiar na Pi co 30 s):

| Parametr | Wynik | Kryterium T4 |
|----------|-------|--------------|
| Klatki odebrane / brakujące / błędne | 72 077 / 0 (0,00%) / 0; luki `seq` 0 | — |
| FPS (`t_sensor`) | 120,12 (w każdym oknie 60 s) | 120 ±1% — **spełnione** |
| Okres `t_sensor` p50 / max | 8,32 / 8,35 ms | — |
| Przepustowość | 221,5 Mbit/s | — |
| `camera_drops` | 0 | — |
| Opóźnienie przechwycenia p50 / max | 15,5 / 21,2 ms | — |
| Czas wysyłki p50 / max | 0,14 / 11,2 ms (max w oknie poza pierwszym: ≤ 1,7 ms) | — |
| CPU | nadajnik ok. 45% jednego rdzenia; cały system 15% (z obsługą sieci) | — |
| Temperatura | 57–61 °C (ustalona po ok. 2 min, bez radiatora) | — |
| Zegar CPU / `get_throttled` | 1,8 GHz przez cały test / `0x0` | brak throttlingu — **spełnione** |

- Testy jednostkowe: 21/21 OK na laptopie (Python 3.10, z `pyzmq`) i na Pi (Python 3.13,
  pyzmq 26.4); bez `pyzmq` 19 OK + 2 pominięte.
- V1: `camera_drops` = 0; `queue_drops` i `stale_drops` pojawiły się tylko przed połączeniem
  odbiornika i po jego zakończeniu (nikt nie odbierał), nie w trakcie odbioru.
- V2: zapisana klatka PGM 640×360 (230 415 B) pokazuje poprawny obraz.
- V3: wynik identyczny z pomiarem z października → refaktoryzacja nie zmieniła toru kamery.

Wnioski:

- Python na Pi 4 utrzymuje 120 fps z wysyłką ZeroMQ, także przez 10 min (T4 spełniony): nadajnik
  zajmuje ok. 45% jednego rdzenia, cały system ok. 15% razem z obsługą sieci (odbiornik na tym
  samym Pi dodaje ok. 9–10% rdzenia); temperatura bez radiatora ustala się na ok. 60 °C. To odpowiada na pytanie z [§9 pkt 4](../docs/specyfikacja.md#9-otwarte-kwestie)
  i na **[DO USTALENIA]** w [§5.4](../docs/specyfikacja.md#54-wiadomości-rpi) — plan B
  (niższa rozdzielczość lub detekcja kropki na RPi) nie jest potrzebny.
- Opóźnienie przechwycenia jest o ok. 1,4 ms większe niż w `camera_check.py` (kopia klatki);
  nie ma to znaczenia, bo czas klatki pochodzi z `SensorTimestamp`, a nie z chwili odbioru.
- Przez Ethernet 1 Gbit: 0 utraconych klatek przy ok. 222 Mbit/s.
- Pomiar na docelowym laptopie nadal do wykonania (#16).
