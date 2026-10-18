# Raspberry Pi — konfiguracja i test kamery

Dotyczy zadania [#6 Konfiguracja RaspberryPi](https://github.com/ZuberRS03/projekt_przejsciowy_PWR/issues/6).
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

Sieć (statyczne IP, wyłączenie WiFi i BT) — do zrobienia po przejściu na wydzielony router;
obecnie SSH działa po WiFi.

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
