# Laptop — synchronizacja zegarów (issue #14)

Ten katalog zawiera odbiornik UDP na **laptop Windows** oraz model zegara ESP32 względem
`CLOCK_MONOTONIC` Raspberry Pi. Wykorzystuje **istniejące** pakiety `SYNC_REPORT`
wychodzące z ESP32. Kod ESP32 i serwera RPi pozostaje bez zmian.

## Struktura

```text
laptop/
├── receiver.py              # UDP 5000: IMU, SHOT, STATUS, SYNC_REPORT
├── clock_sync.py            # okno 60 s, filtr RTT, regresja, konwersja czasu
├── tests/
│   └── test_clock_sync.py   # testy jednostkowe na danych syntetycznych
└── README.md
```

## Uruchomienie (PowerShell w katalogu głównym repozytorium)

1. Upewnij się, że ESP32 wysyła UDP do laptopa `192.168.50.20:5000`,
   a serwer synchronizacji RPi działa pod `192.168.50.10:5001`.
2. **Zamknij** stary `esp32/shooting-trainer-esp32/tools/udp_receiver.py`.
   Tylko jeden odbiornik może zajmować port UDP 5000 na laptopie.
3. Uruchom testy jednostkowe:

   ```powershell
   python -m unittest discover -s laptop/tests -v
   ```

4. Uruchom nowy odbiornik:

   ```powershell
   python laptop/receiver.py --csv laptop/logs/sync.csv
   ```

   `--csv` jest opcjonalne; przechowuje raporty do późniejszej analizy. Folder `logs/`
   należy ignorować w repozytorium.

5. Obserwuj przez 70–90 sekund. Przez pierwsze raporty zobaczysz `[SYNC] WAITING`,
   a po zebraniu 10 **przefiltrowanych** pomiarów `[SYNC] READY`.
   Gdy filtr odrzuca wiele raportów, osiągnięcie READY może potrwać dłużej.

## Zasada działania, zgodna z §4.3 specyfikacji

- `t1`, `t4` — ESP32 (`esp_timer_get_time()`), mikrosekundy.
- `t2`, `t3` — Raspberry Pi (`CLOCK_MONOTONIC`), nanosekundy.
- `RTT = (t4-t1) - (t3-t2)/1000`, jednostka µs.
- Punkty regresji: `x=(t1+t4)/2`, `y=(t2+t3)/2000` (µs).
- Utrzymywane jest okno 60 s, filtr `RTT <= min(RTT) + 1000 µs`.
  Pomiar wygasa również bez nowych SYNC_REPORT, gdy nadal przychodzą dane IMU/STATUS.
- Regresja liniowa: `t_rpi_us = a * t_esp_us + b`.
- Model jest gotowy po co najmniej 10 pomiarach po filtracji.
- Wykrycie restartu ESP32 (spadek epoki i sekwencji) zeruje model.

Wynik `t_rpi_ns` jest w nanosekundach zegara RPi, czyli w domenie czasu
metadanych `SensorTimestamp` kamery. Nie jest to czas kalendarzowy.

## Diagnostyka

- `[RECEIVER]`: pakiety/s, próbki/s, raporty/s, luki w `seq`, błędy pakietów.
- `[SYNC] WAITING`: model ma mniej niż 10 pomiarów po filtracji.
- `[SYNC] READY`: aktualne parametry `a`, `b`, dryf w ppm i RMS reszt w µs.
- `[IMU]`: timestamp ESP oraz timestamp przeliczony na zegar RPi (lub UNSYNCED).
- `[SHOT]`: jedno zdarzenie po usunięciu duplikatów, przeliczenie czasu jeśli READY.
- `[RESTART]`: wykryto restart ESP32; dane poprzedniej epoki odrzucone.

**RMS reszt NIE jest dokładnością synchronizacji.** Rzeczywisty błąd wymaga
niezależnego pomiaru zgodnego z testem T1 specyfikacji, najlepiej wspólnym
sygnałem elektrycznym rejestrowanym przez dwa urządzenia. Nie deklarujemy
osiągnięcia 1 ms na podstawie samego modelu.

## Sposób sprawdzenia zadania #14

- [ ] Testy jednostkowe modelu przechodzą bez błędów.
- [ ] Po uruchomieniu odbiornika jest `SYNC_REPORT` i model przechodzi w READY.
- [ ] Wyświetlane są RTT, dryf, współczynnik a i offset b.
- [ ] Timestamp IMU przelicza się na zegar RPi; SHOT po teście także.
- [ ] Zatrzymanie serwera RPi nie zatrzymuje IMU; model może korzystać z
      ostatniego dopasowania tylko dopóki dane mieszczą się w oknie.
- [ ] Po restarcie ESP32 model wraca do WAITING i ponownie przechodzi w READY.
- [ ] Odbiór danych nie jest blokowany przez obliczenia modelu.

Dane wideo i korelacja z klatkami zostają na później (issue #16).
