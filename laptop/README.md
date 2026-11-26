# Laptop — synchronizacja i korelacja strumieni (issue #14 + #16)

Ten katalog zawiera program uruchamiany **na laptopie Windows**. Łączy pakiety UDP
z ESP32 (`IMU`, `SHOT`, `STATUS`, `SYNC_REPORT`) oraz klatki z Raspberry Pi
(`VIDEO_FRAME`, ZeroMQ PULL). Podstawą czasową jest `CLOCK_MONOTONIC` RPi.

**Zakres #16:** komunikacja, buforowanie, korelacja czasowa i diagnostyka.
**Poza zakresem:** wykrywanie punktu laserowego, analiza obrazu i kalibracja C.

## Pliki

```text
laptop/
├── receiver.py             # istniejący odbiornik UDP + clock_sync (#14)
├── clock_sync.py           # istniejący model ESP32 -> RPi (#14)
├── video_stream.py         # NOWE: odbiór/validacja ZeroMQ VIDEO_FRAME
├── correlation.py          # NOWE: watermark, bufory, powiązanie SHOT/IMU z klatką
├── integrated_receiver.py  # NOWE: uruchomienie UDP + ZeroMQ + logowanie wyników
├── .gitignore
├── tests/
│   ├── test_clock_sync.py
│   ├── test_receiver.py
│   ├── test_correlation.py
│   ├── test_video_stream.py
│   └── test_integration16.py
└── README.md
```

Nie modyfikujemy firmware ESP32 ani skryptów RPi. Zachowujemy `receiver.py`
i `clock_sync.py` z działającego zadania #14.

## Krok 1 — sprawdzenie urządzeń

- ESP32: `192.168.50.30` (Wi-Fi); wysyła UDP do `192.168.50.20:5000`.
- RPi: `192.168.50.10` (Ethernet); `sync-responder.service` obsługuje UDP 5001;
  `video-sender.service` nadaje klatki po `tcp://192.168.50.10:5555`.
- Laptop: `192.168.50.20` (Ethernet).

Na laptopie uruchom PowerShell:

```powershell
ssh admin@192.168.50.10
```

Na RPi:

```bash
sudo systemctl status sync-responder.service
sudo systemctl status video-sender.service
```

Obie usługi powinny mieć `active (running)`. Jeżeli kamera nie nadaje, sprawdź:

```bash
sudo journalctl -u video-sender.service -n 50 --no-pager
```

W razie potrzeby usługę nadajnika można uruchomić przez
`sudo systemctl start video-sender.service`. Restart RPi nie jest potrzebny.

## Krok 2 — instalacja i testy na laptopie

PowerShell, **w głównym katalogu `projekt_przejsciowy_PWR`**:

```powershell
python -m pip install pyzmq
python -m unittest discover -s laptop/tests -v
```

Nie uruchamiaj równolegle starego odbiornika UDP (`esp32/.../udp_receiver.py`)
ani `laptop/receiver.py` z `integrated_receiver.py`, ponieważ port UDP `5000`
może być zajęty tylko przez jeden proces. Podobnie odbiornik `rpi/video_receiver.py`
nie powinien działać równolegle (ZeroMQ PULL rozdziela klatki pomiędzy odbiorcami).

## Krok 3 — uruchomienie całości

```powershell
python laptop/integrated_receiver.py --sync-csv laptop/logs/sync.csv --matches-csv laptop/logs/matches.csv
```

Opcjonalnie, aby zapisać ostatni surowy obraz do pliku PGM i upewnić się, że bajty
Y8 docierają poprawnie:

```powershell
python laptop/integrated_receiver.py --save-last-pgm laptop/logs/last_frame.pgm
```

PGM to prosty obraz w skali szarości (640 × 360), który można otworzyć m.in.
w programach graficznych obsługujących format PGM. Zapis następuje po `Ctrl+C`.
W normalnym trybie program **nie gromadzi bajtów obrazów**: buforuje jedynie
metadane, co pozwala uniknąć zużywania pamięci przy ~120 fps × 230 KB.

## Krok 4 — test funkcjonalny

1. Zostaw ESP32 i RPi włączone oraz — przy obecnym firmware — otwarty Serial Monitor
   ESP32 (wcześniej test bez monitora ujawnił okresowe przerwy w transmisji).
2. Uruchom program i sprawdź, czy `[VIDEO] frames/s` wynosi w przybliżeniu 120,
   `[RECEIVER] IMU samples/s` około 100, a `[RECEIVER] SYNC/s` około 1.
3. Po zebraniu co najmniej 10 raportów SYNC po filtracji powinno pojawić się
   `[SYNC] READY`.
4. Zarejestruj 2–3 pojedyncze zdarzenia spustu w kontrolowanych warunkach.
   Oczekuj wierszy `[MATCH] shot=... frame=... delta(frame-shot)=... ms`.
5. Sprawdź `laptop/logs/matches.csv`: `status=MATCH`, `frame_seq`, timestamp
   strzału RPi oraz różnica czasowa (ze znakiem).
6. Zweryfikuj, że `missing_frame_seq`, `invalid`, `queue_drops` nie rosną
   w czasie stabilnego testu (docelowe progi strat są w osobnym teście T3).
7. Sprawdź restart ESP32: model powinien wrócić do `WAITING`; nowe strzały
   przed odzyskaniem modelu będą oznaczone jako `UNSYNCED`, a nie błędnie dopasowane.

Zakończenie: `Ctrl+C`. Program podsumuje liczbę pakietów, klatek, strat i wyników korelacji.

## Format VIDEO_FRAME (rzeczywisty kod RPi)

W `rpi/protocol.py` jest `VIDEO_FRAME_HEADER = '<HBBIqIqIIIHHHB'`, 47 B,
w kolejności: nagłówek wspólny 16 B oraz `frame_seq`, `t_sensor_ns`, `exposure_us`,
`frame_duration_us`, `line_time_ns`, `width`, `height`, `sensor_rows`, `format`.
Druga część wiadomości to `width × height` bajtów obrazu Y8. Odbiornik sprawdza
rozmiar, wersję, `magic`, typ i format. Funkcja `decode_parts()` odtwarza metadane.

Luki **`frame_seq`** mogą oznaczać również klatki odrzucone po stronie kamery/RPi;
luki **`seq` nagłówka** to brakujące wysłane wiadomości (obydwa są raportowane osobno).
Przerwanie/restart nadajnika wideo zostaje rozpoznane po jego zresetowanych licznikach.

## Watermark i dokładność

Korelacja jest zgodna z `docs/specyfikacja.md`, §6.2–6.3:

```text
T = t_RPi(SHOT)  (z modelu synchronizacji #14)
t_center = t_sensor_ns + sensor_rows/2 × line_time_ns + exposure_us × 1000/2 + C
watermark: najnowsze t_sensor_ns > T + frame_duration_us × 1000
wybór: minimalizuj |t_center − T|
```

`C=0` i `y=height/2`, ponieważ **nie analizujemy obrazu**. Rzeczywista
korekta toru czasowego i wiersza, w którym jest kropka lasera, wymaga testu
T2 i należy do prac wizyjnych. Stosujemy bufor metadanych 4 s oraz
maksymalną akceptowaną różnicę 25 ms (`--max-delta-ms`), aby nie dopasowywać
strzałów do bardzo odległych klatek. Po 5 s bez możliwości rozstrzygnięcia
występuje `VIDEO_TIMEOUT`.

Wyniki zawierają:
- `MATCH`: dopasowano klatkę i obliczono `delta_frame_minus_shot_ns`;
- `UNSYNCED`: brak aktualnego modelu, nie przypisujemy klatki;
- `NO_NEAR_FRAME`: najbliższa dostępna klatka poza ustawioną tolerancją;
- `VIDEO_TIMEOUT`: nie było klatki umożliwiającej rozstrzygnięcie;
- `ESP_RESTART`: przerwano oczekiwanie po zmianie epoki zegara ESP;
- `END_WITHOUT_FRAME`: program wyłączono, zanim nastąpiło rozstrzygnięcie.

Do `matches.csv` trafia także jakość modelu `SYNC` z momentu zdarzenia:
liczba pomiarów, minimalny RTT, dryf i RMS reszt. **RMS reszt nie jest
niezależnym pomiarem rzeczywistej dokładności synchronizacji.**

Bufor IMU przechowuje przeliczone czasy ostatnich 4 s, aby dla dopasowanego
strzału wskazać najbliższą próbkę IMU (jeśli w odległości do 20 ms).

## Parametry

```powershell
python laptop/integrated_receiver.py --help
```

Najważniejsze: `--video tcp://192.168.50.10:5555`, `--frame-history-s 4`,
`--max-delta-ms 25`, `--max-wait-s 5`, `--save-last-pgm PATH`,
`--sync-csv PATH`, `--matches-csv PATH`.

## Gdy wideo nie przychodzi

1. Sprawdź `sudo systemctl status video-sender.service` na RPi.
2. Sprawdź `sudo journalctl -u video-sender.service -n 50 --no-pager`.
3. Sprawdź czy laptop i RPi widzą się w sieci (`ping 192.168.50.10`).
4. Nie uruchamiaj drugiego odbiornika PULL równolegle — wiadomości z PUSH
   będą rozdzielane między odbiorców.
5. Przy testach bez kamery możesz zatrzymać usługę i uruchomić na RPi
   `cd ~/projekt/rpi && python3 video_sender.py --fake --seconds 60`
   (przedtem `sudo systemctl stop video-sender.service`). Po teście
   przywróć usługę przez `sudo systemctl start video-sender.service`.
6. Pamiętaj, że bez `SYNC READY` strzały są logowane jako `UNSYNCED` nawet przy
   poprawnie nadchodzących klatkach.

## Definicja wykonania #16

- [ ] Laptop jednocześnie otrzymuje UDP ESP32 i ZeroMQ z RPi.
- [ ] Każda poprawna klatka ma numer i timestamp, a wideo Y8 jest możliwe do zapisania PGM.
- [ ] Liczniki strat `seq`, `frame_seq`, `queue_drops` i `invalid` są raportowane.
- [ ] SHOT są dopasowywane do klatek po timestampach RPi (po watermark).
- [ ] Wynik zawiera różnicę czasową i diagnostykę synchronizacji, również przy brakach.
- [ ] Testy jednostkowe i lokalny test ZeroMQ przechodzą bez błędów.
- [ ] Potwierdzono poprawność w krótkim teście na sprzęcie.
