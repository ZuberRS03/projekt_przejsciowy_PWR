# projekt_przejsciowy_PWR

System treningowy z repliką broni: replika z ESP32 (akcelerometr, spust, wskaźnik laserowy),
kamera na Raspberry Pi 4B oraz laptop, który w czasie rzeczywistym łączy dane z obu źródeł.

## Warstwa komunikacji i Raspberry Pi

Pełna specyfikacja: [docs/specyfikacja.md](docs/specyfikacja.md).

Najważniejsze założenia:

- **Znaczniki czasu u źródła** — każda próbka IMU, zdarzenie spustu i klatka wideo jest
  oznaczana w momencie powstania.
- **Zegar referencyjny: Raspberry Pi** (`CLOCK_MONOTONIC`, ten sam co znaczniki kamery).
  ESP32 wysyła surowe `esp_timer_get_time()`, a laptop przelicza je do czasu RPi na podstawie
  wymiany synchronizacyjnej typu NTP (co 1 s, filtracja + regresja offsetu i dryfu).
- **Kamera 120 fps** (Camera Module 3, tryb 1536×864) — warunek konieczny dokładności
  dopasowania strzału do klatki 5–10 ms.
- **Sieć wydzielona:** ESP32 po WiFi 2.4 GHz, RPi i laptop po Ethernecie 1 Gbit.

| Połączenie | Transport | Zawartość |
|------------|-----------|-----------|
| ESP32 → laptop | UDP 5000 | próbki IMU, strzały, raporty synchronizacji |
| ESP32 ↔ RPi | UDP 5001 | wymiana synchronizacyjna |
| RPi → laptop | ZeroMQ PUSH/PULL, tcp 5555 | klatki wideo z metadanymi czasu |
