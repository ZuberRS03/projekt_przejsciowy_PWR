"""Wspólna konfiguracja kamery RPi: Camera Module 3 (IMX708), 1536x864 @ 120 fps.

Moduł nie importuje picamera2 - funkcje dostają obiekt Picamera2 jako argument.
"""

SENSOR_SIZE = (1536, 864)
LORES_SIZE = (640, 360)
FRAME_US = 8333  # 120 fps
SENSOR_ROWS = SENSOR_SIZE[1]
# Czas odczytu wiersza IMX708 w trybie 1536x864: hblank 3680 (tylko do odczytu), pixel_rate 566,4 MHz
# -> (1536 + 3680) / 566,4e6 s = 9209 ns. Kontrola: (864 + 40 vblank) wierszy * 9,209 us = 8325 us
# = FrameDuration z metadanych.
LINE_TIME_NS = 9209

DEFAULT_EXPOSURE_US = 2000
DEFAULT_GAIN = 4.0
DEFAULT_LENS_POSITION = 0.5  # dioptrie (1/m), 0 = nieskończoność


def configure(picam2, exposure_us, gain, lens_position):
    """Konfiguruje kamerę: stała ekspozycja/wzmocnienie, ręczne ogniskowanie, strumień lores 640x360."""
    config = picam2.create_video_configuration(
        main={"size": SENSOR_SIZE, "format": "YUV420"},
        lores={"size": LORES_SIZE, "format": "YUV420"},
        raw={"size": SENSOR_SIZE},
        buffer_count=6,
        controls={
            "FrameDurationLimits": (FRAME_US, FRAME_US),
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": exposure_us,
            "AnalogueGain": gain,
            "AfMode": 0,  # manual
            "LensPosition": lens_position,
        },
    )
    picam2.configure(config)
