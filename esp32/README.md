# ESP32-C3 — konfiguracja, akwizycja danych i transmisja UDP

Dotyczy m.in. zadania [#10 Uruchomienie ESP32](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/10). Założenia komunikacji i synchronizacji opisano w [`docs/specyfikacja.md`](../../docs/specyfikacja.md).

ESP32-C3 stanowi moduł pomiarowo-komunikacyjny trenażera. Odczytuje akcelerometr i żyroskop, wykrywa sygnał spustu oraz wysyła dane przez Wi-Fi do **laptopa**, który obecnie wykonuje odbiór i dalsze przetwarzanie. Raspberry Pi będzie źródłem danych kamery i zegarem referencyjnym — synchronizacja z nim **nie jest jeszcze zaimplementowana**.

## Stan urządzenia

| Element | Konfiguracja / stan |
|---------|---------------------|
| Płytka | DFRobot Beetle ESP32-C3 V2.0.0 |
| Środowisko | Visual Studio Code + PlatformIO |
| Framework | Arduino (obecna implementacja) |
| Board ID | `dfrobot_beetle_esp32c3` |
| USB / Serial Monitor | USB-C z transmisją danych, `115200` baud (podczas testów `COM3`) |
| IMU | Moduł sprzedawany jako MPU-6050, adres I²C `0x68`, `WHO_AM_I = 0x72` |
| Odczyt IMU | 100 Hz, `DATA_RDY`, 6 osi jako surowe `int16_t` |
| Sygnał spustu | PC817 → GPIO7, zbocze `RISING`, debouncing 100 ms |
| Wi-Fi | `mgr_zuber`, 2,4 GHz |
| MAC ESP32 | `10:B4:1D:22:82:A8` |
| IP ESP32 | `192.168.50.30` (rezerwacja DHCP na routerze) |
| Router | `192.168.50.1` |
| Laptop — odbiornik | `192.168.50.20`, UDP `5000` (adres musi odpowiadać aktualnej konfiguracji laptopa) |

## Połączenia układu

| Sygnał | Pin ESP32-C3 | Uwagi |
|--------|---------------|-------|
| MPU SDA | GPIO4 | I²C, dane |
| MPU SCL | GPIO5 | I²C, zegar |
| MPU INT | GPIO6 | `DATA_RDY`, przerwanie na zboczu narastającym |
| Wyjście PC817 | GPIO7 | Przerwanie spustu na zboczu narastającym |
| MPU VCC / GND | Zasilanie modułu / wspólna masa elektroniki | Sprawdzić napięcie i zgodność poziomów logicznych z ESP32 (3,3 V) |

Układ repliki jest odseparowany galwanicznie od elektroniki ESP32 za pomocą PC817. Na wejściu GPIO7 zastosowano zewnętrzny rezystor podciągający 10 kΩ. Wskaźnik laserowy ma niezależne zasilanie i nie jest sterowany przez ESP32.

**Uwaga o zasilaniu:** podczas diagnostyki zmierzono ok. 4 V pomiędzy VCC i GND płytki IMU oraz ok. 3,3 V na liniach SDA/SCL w spoczynku. Nie oznacza to, że 4 V można podawać bezpośrednio na dowolne wejście ESP32. Przed zmianą zasilania należy sprawdzić konkretny moduł i jego stabilizator; nie łączyć bezpośrednio masy repliki z masą ESP32.

## Konfiguracja i uruchomienie projektu

Otworzyć w VS Code **folder zawierający `platformio.ini`**, tj. `esp32/shooting-trainer-esp32/` (a nie tylko katalog główny repozytorium). Pozwala to PlatformIO prawidłowo odnaleźć framework i biblioteki.

Podstawowa konfiguracja `platformio.ini`:

```ini
[env:dfrobot_beetle_esp32c3]
platform = espressif32
board = dfrobot_beetle_esp32c3
framework = arduino
monitor_speed = 115200

build_flags =
    -DARDUINO_USB_CDC_ON_BOOT=1
```

Wcześniejsze testy używały `lib_deps = adafruit/Adafruit MPU6050`. **Aktualny `main.cpp` czyta rejestry przez `Wire.h` bez biblioteki Adafruit**, więc ta zależność nie jest wymagana przez obecną wersję programu (może nadal znajdować się w lokalnym `platformio.ini`).

### Konfiguracja Wi-Fi

Przed kompilacją należy utworzyć lokalnie `include/wifi_credentials.h`:

```cpp
#pragma once

const char* WIFI_SSID = "mgr_zuber";
const char* WIFI_PASSWORD = "TUTAJ_WPISZ_HASLO";
```

Prawdziwy plik z hasłem **nie może trafić do repozytorium**. W `.gitignore` powinna być reguła:

```gitignore
/include/wifi_credentials.h
```

Adres `192.168.50.30` jest rezerwowany na routerze dla MAC ESP32; nie został wpisany na sztywno w firmware. W `src/main.cpp` odbiornik jest ustawiony jako `LAPTOP_IP(192, 168, 50, 20)` i `LAPTOP_PORT = 5000` — w razie innego IP laptopa trzeba go zaktualizować. Program automatycznie wznawia łączność Wi-Fi; po nawiązaniu połączenia wyłącza oszczędzanie energii radia (`WiFi.setSleep(false)`).

### Wgranie firmware

1. Podłączyć ESP32 do laptopa kablem USB-C obsługującym **transmisję danych**.
2. W PlatformIO wykonać **Build**, a następnie **Upload** (zatrzymać wcześniej Serial Monitor, jeśli blokuje port).
3. Otworzyć **Serial Monitor** z prędkością `115200`; w razie potrzeby nacisnąć przycisk `RST`.
4. Sprawdzić `WHO_AM_I: 0x72`, komunikaty o inicjalizacji oraz połączeniu Wi-Fi.

Program jest zapisany w pamięci Flash i uruchamia się ponownie po odłączeniu i przywróceniu zasilania. Port COM może być inny niż podczas wcześniejszych testów.

## MPU-6050 — identyfikator `0x72`

Podczas wstępnych testów skaner I²C wykrywał czujnik pod adresem `0x68`, lecz rejestr `WHO_AM_I` zwracał **`0x72`**, a nie `0x68` oczekiwane przez bibliotekę Adafruit MPU6050. Z tego powodu inicjalizacja przez `Adafruit_MPU6050::begin()` nie przechodziła.

**Obejście użyte we wcześniejszym programie testowym Adafruit:** w lokalnym pliku biblioteki:

```text
.pio/libdeps/dfrobot_beetle_esp32c3/Adafruit MPU6050/Adafruit_MPU6050.h
```

zmieniano:

```cpp
#define MPU6050_DEVICE_ID 0x68
```

na:

```cpp
#define MPU6050_DEVICE_ID 0x72
```

Ta zmiana była tylko obejściem diagnostycznym: katalog `.pio/` nie jest śledzony przez Git i może zostać odtworzony podczas instalacji zależności. **Nie trzeba wykonywać tej zmiany dla aktualnej wersji `src/main.cpp`** — kod korzysta z `Wire.h`, sprawdza `WHO_AM_I` (`0x68` albo `0x72`) i samodzielnie konfiguruje rejestry czujnika. Zgodność zamiennika z oryginalnym MPU-6050 jest potwierdzona tylko w zakresie przeprowadzonych testów.

## Działanie aktualnego programu

### Akwizycja IMU

- Magistrala I²C: 400 kHz; zakresy pomiarowe: akcelerometr ±2 g, żyroskop ±250°/s.
- Częstotliwość nominalna: **100 Hz** (`SMPLRT_DIV = 9`, ustawiony filtr DLPF).
- Sygnał `DATA_RDY` na GPIO6 wyzwala przerwanie; ISR przypisuje czas `esp_timer_get_time()` i umieszcza go w kolejce FreeRTOS.
- Poza ISR odczytywane jest 14 bajtów rejestrów MPU (6 osi + temperatura); temperatura nie jest przesyłana.
- Do transmisji trafia 6 **surowych** wartości `int16_t` i timestamp `int64_t` dla każdej próbki.
- Pięć próbek jest łączonych w jeden pakiet IMU; liczniki pozwalają wykrywać błędy I²C i pominięcia w kolejce.

### Sygnał spustu

- Przy zasilonej replice stan spoczynkowy GPIO7 wynosi **LOW**, a sygnał aktywacji pojawia się jako **HIGH**.
- ISR na zboczu `RISING` zapisuje czas pierwszego impulsu.
- Debouncing **100 ms** ignoruje kolejne impulsy w tym oknie, zachowując timestamp pierwszego zaakceptowanego zbocza.
- Każde przyjęte zdarzenie otrzymuje `shot_id` i jest trzykrotnie wysyłane jako `SHOT`: bez zwłoki i z harmonogramem +5 ms, +10 ms. Odbiornik eliminuje duplikaty po `shot_id`.

Rejestrowany jest czas elektrycznego sygnału spustu, **nie zweryfikowany czas opuszczenia lufy przez kulkę**.

### Komunikacja UDP z laptopem

| Typ | Kierunek | Zawartość |
|-----|----------|-----------|
| `IMU` (1) | ESP32 → laptop:5000 | 5 próbek, każda po 20 B (`t_us`, `ax`, `ay`, `az`, `gx`, `gy`, `gz`) |
| `SHOT` (2) | ESP32 → laptop:5000 | `shot_id`, `t_shot_us`, numer powtórzenia |
| `STATUS` (6) | ESP32 → laptop:5000 | RSSI, flaga Wi-Fi, licznik pominięć IMU; `battery_mv=0` (pomiar niezaimplementowany) |

Wiadomości mają wspólny nagłówek 16 B (`magic=0x5052`, `version=1`, `type`, `seq`, `t_send`). Pola są przesyłane w formacie **little-endian**. Pakiet z pięcioma próbkami IMU ma 120 B, `SHOT` 32 B, a `STATUS` 24 B. Przesyłane wartości IMU nie są jeszcze skalibrowane.

### Odbiornik Python na laptopie

Po podłączeniu laptopa do routera (Ethernet) uruchomić w katalogu projektu:

```powershell
python tools/udp_receiver.py
```

Odbiornik korzysta wyłącznie ze standardowej biblioteki Pythona, nasłuchuje na `0.0.0.0:5000`, dekoduje `IMU`, `SHOT`, `STATUS`, wyświetla statystyki i wskazuje braki numerów `seq`. W zaporze Windows należy dopuścić ruch przychodzący UDP 5000 w sieci prywatnej. Następnie uruchomić firmware ESP32 i Serial Monitor.

Przykładowy oczekiwany komunikat:

```text
[RECEIVER] pakiety/s=21 | probki/s=100 | braki seq=0 | invalid=0
```

Dla jednego zdarzenia spustu odbiornik powinien pokazać jeden `SHOT` oraz dwa wpisy `SHOT DUPLICATE` (`repeat=1`, `repeat=2`). `seq=0` braków oznacza brak wykrytych luk **w wysłanych pakietach UDP**, a nie gwarantuje, że nie pominięto żadnej próbki jeszcze przed transmisją.

## Wyniki przeprowadzonych testów

| Test | Wynik |
|------|-------|
| Pierwsze uruchomienie i Wi-Fi (24.10.2026) | Build/Upload OK; `ping 192.168.50.30`: 4/4 odpowiedzi, 0% strat |
| Zasilanie i I²C IMU (19.11.2026) | Odpowiedź `0x68`, `WHO_AM_I=0x72`; odczyty akcelerometru i żyroskopu reagują na ruch |
| Stabilność IMU (22.11.2026) | Około 100–101 próbek/s; odstęp ok. 9985 µs; w teście akwizycji 0 błędów I²C i 0 nowych `IRQ drops` |
| Debouncing spustu (22.11.2026) | Okno 100 ms; w serii czterech testów po jednym zaakceptowanym zdarzeniu na aktywację |
| Transmisja IMU/STATUS przez UDP (22.11.2026) | Około 21–22 pakiety/s i 100–105 próbek/s w sekundowych oknach odbiornika; 0 braków `seq`, 0 błędów dekodowania w pokazanych logach |
| Transmisja SHOT (22.11.2026) | 5/5 zdarzeń odebranych; po 3 wiadomości na zdarzenie (`repeat=0,1,2`), deduplikacja działa |

W teście łączności licznik `imuSkipped` osiągnął **4**, ale nie zwiększał się podczas późniejszych obserwacji. Wymaga to dalszych testów obciążeniowych; prawidłowy odbiór UDP nie oznacza jeszcze niezawodności wymaganej dla całego systemu.

## Ograniczenia i dalsze prace

- Synchronizacja zegara ESP32 z referencyjnym zegarem Raspberry Pi (`SYNC_REQ`/`SYNC_RESP`/`SYNC_REPORT`, UDP 5001): responder na RPi jest gotowy ([#12](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/12), [rpi/README.md](../rpi/README.md#responder-synchronizacji-czasu--sync_responderpy)); strona ESP32 pozostaje **do wykonania** ([#13](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/13)).
- Kalibracja IMU oraz walidacja jego dokładności i charakterystyki zamiennika `WHO_AM_I=0x72` — do wykonania.
- Należy zweryfikować odporność komunikacji na zerwanie Wi-Fi, restarty i długotrwałą pracę, a także wykrywanie utraty próbek przed wysyłką.
- Trzykrotna transmisja `SHOT` **nie gwarantuje** dostarczenia zdarzenia przy utracie sieci (brak ACK i trwałego bufora).
- Analiza obrazu i ocena strzału są poza zakresem modułu ESP32.
