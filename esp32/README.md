# ESP32-C3 — konfiguracja i test połączenia Wi-Fi

Dotyczy zadania [#10 Uruchomienie ESP32](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/10).

Moduł ESP32-C3 stanowi część pomiarowo-komunikacyjną trenażera strzeleckiego. Na obecnym etapie uruchomiono płytkę i skonfigurowano jej łączność z wydzieloną siecią Wi-Fi. Obsługa czujników i przesyłanie danych do Raspberry Pi będą realizowane w kolejnych etapach.

## Stan urządzenia

| Element | Wartość |
|---------|---------|
| Płytka | DFRobot Beetle ESP32-C3 V2.0.0 |
| Środowisko | Visual Studio Code + PlatformIO |
| Framework | Arduino |
| Konfiguracja płytki | `dfrobot_beetle_esp32c3` |
| Port USB podczas testów | `COM3` (może się zmienić) |
| Serial Monitor | `115200` baud |
| Sieć Wi-Fi | `mgr_zuber` (2,4 GHz) |
| Adres MAC | `10:B4:1D:22:82:A8` |
| Zarezerwowany adres IP | `192.168.50.30` |
| Brama sieciowa | `192.168.50.1` |

## Konfiguracja projektu

Oprogramowanie znajduje się w `src/main.cpp`. Projekt korzysta z frameworka Arduino i biblioteki `WiFi.h` dostępnej dla ESP32.

Najważniejsze ustawienia z pliku `platformio.ini`:

```ini
[env:dfrobot_beetle_esp32c3]
platform = espressif32
board = dfrobot_beetle_esp32c3
framework = arduino
monitor_speed = 115200

build_flags =
    -DARDUINO_USB_CDC_ON_BOOT=1
```

Dane dostępowe do Wi-Fi przechowywane są lokalnie w pliku `include/wifi_credentials.h`, który jest wykluczony ze śledzenia przez `.gitignore`. Przed kompilacją należy utworzyć ten plik z własnymi danymi:

```cpp
#pragma once

const char* WIFI_SSID = "mgr_zuber";
const char* WIFI_PASSWORD = "TUTAJ_WPISZ_HASLO";
```

## Działanie programu

Po uruchomieniu ESP32:

1. Inicjalizuje komunikację szeregową przez USB.
2. Uruchamia interfejs Wi-Fi w trybie klienta (`WIFI_STA`).
3. Łączy się z siecią `mgr_zuber`.
4. Wyświetla w Serial Monitor adres MAC, IP, bramę i siłę sygnału (RSSI).
5. Po utracie połączenia podejmuje próby ponownego połączenia (w kodzie: co 15 s, dodatkowo włączone `setAutoReconnect(true)`).

Program zapisany jest w pamięci Flash, więc po odłączeniu zasilania i ponownym uruchomieniu ESP32 ponownie podejmuje próbę połączenia z Wi-Fi.

### Stały adres IP

Adres `192.168.50.30` jest **rezerwacją DHCP na routerze** dla MAC `10:B4:1D:22:82:A8`. Nie jest ustawiony na sztywno w kodzie. Dzięki temu router przydziela ten sam adres po kolejnych połączeniach — o ile rezerwacja pozostaje aktywna i urządzenie korzysta z tej sieci.

## Uruchomienie i weryfikacja

W VS Code, korzystając z PlatformIO:

1. Podłączyć płytkę do komputera **kablem USB-C obsługującym transmisję danych**.
2. Uruchomić **Build**, a następnie **Upload**.
3. Otworzyć **Serial Monitor** (`115200` baud); w razie potrzeby nacisnąć przycisk `RST` na płytce.
4. Sprawdzić komunikat potwierdzający połączenie i przydzielony adres IP.
5. Na komputerze w tej samej sieci wykonać:

```powershell
ping 192.168.50.30
```

### Wynik testu (24.10.2026)

- Kompilacja i wgranie programu: **zakończone sukcesem**.
- Połączenie z siecią `mgr_zuber`: **potwierdzone**.
- Rezerwacja DHCP `192.168.50.30`: **skonfigurowana na routerze**.
- Test `ping`: **4 odpowiedzi na 4 pakiety, 0% strat** (średnio 49 ms).

## Dalsze prace

W kolejnych zadaniach planowane jest podłączenie MPU-6050 i sygnału czujnika spustu oraz przesyłanie pomiarów do Raspberry Pi. Funkcje te **nie są jeszcze częścią opisanej implementacji**.
