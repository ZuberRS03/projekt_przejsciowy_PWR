
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "wifi_credentials.h"

// =====================================
// Konfiguracja
// =====================================

constexpr uint8_t MPU_ADDR = 0x68;

constexpr int PIN_SDA = 4;
constexpr int PIN_SCL = 5;
constexpr int PIN_IMU_INT = 6;
constexpr int PIN_TRIGGER = 7;

constexpr int64_t DEBOUNCE_US = 100000;
constexpr int64_t SHOT_REPEAT_US = 5000;
constexpr uint8_t IMU_BATCH_SIZE = 5;

const IPAddress LAPTOP_IP(192, 168, 50, 20);
constexpr uint16_t LAPTOP_PORT = 5000;

constexpr uint16_t MAGIC = 0x5052;
constexpr uint8_t VERSION = 1;

constexpr uint8_t TYPE_IMU = 1;
constexpr uint8_t TYPE_SHOT = 2;
constexpr uint8_t TYPE_STATUS = 6;

// Rejestry MPU
constexpr uint8_t REG_SMPLRT_DIV = 0x19;
constexpr uint8_t REG_CONFIG = 0x1A;
constexpr uint8_t REG_GYRO_CONFIG = 0x1B;
constexpr uint8_t REG_ACCEL_CONFIG = 0x1C;
constexpr uint8_t REG_INT_PIN_CFG = 0x37;
constexpr uint8_t REG_INT_ENABLE = 0x38;
constexpr uint8_t REG_INT_STATUS = 0x3A;
constexpr uint8_t REG_ACCEL_XOUT_H = 0x3B;
constexpr uint8_t REG_PWR_MGMT_1 = 0x6B;
constexpr uint8_t REG_PWR_MGMT_2 = 0x6C;
constexpr uint8_t REG_WHO_AM_I = 0x75;

// =====================================
// Protokol binarny
// =====================================

struct __attribute__((packed)) PacketHeader {
    uint16_t magic;
    uint8_t version;
    uint8_t type;
    uint32_t seq;
    int64_t t_send;
};

struct __attribute__((packed)) ImuSample {
    int64_t t_us;
    int16_t ax, ay, az;
    int16_t gx, gy, gz;
};

struct __attribute__((packed)) ImuPacket {
    PacketHeader header;
    uint8_t count;
    uint8_t range;
    uint16_t reserved;
    ImuSample data[IMU_BATCH_SIZE];
};

struct __attribute__((packed)) ShotPacket {
    PacketHeader header;
    uint32_t shot_id;
    int64_t t_shot_us;
    uint8_t repeat;
    uint8_t reserved[3];
};

struct __attribute__((packed)) StatusPacket {
    PacketHeader header;
    uint16_t battery_mv;
    int8_t rssi_dbm;
    uint8_t flags;
    uint32_t imu_overruns;
};

static_assert(sizeof(PacketHeader) == 16, "Header size");
static_assert(sizeof(ImuSample) == 20, "IMU sample size");
static_assert(sizeof(ImuPacket) == 120, "IMU packet size");
static_assert(sizeof(ShotPacket) == 32, "SHOT packet size");
static_assert(sizeof(StatusPacket) == 24, "STATUS packet size");

// =====================================
// Stan aplikacji
// =====================================

WiFiUDP udp;

QueueHandle_t imuQueue = nullptr;
QueueHandle_t triggerQueue = nullptr;

volatile uint32_t imuQueueDrops = 0;
volatile uint32_t triggerQueueDrops = 0;

uint32_t sequenceNumber = 0;
uint32_t nextShotId = 0;

int64_t lastAcceptedShotUs = -1;

ImuPacket imuPacket = {};
uint8_t imuCount = 0;

struct PendingShot {
    bool active = false;
    uint32_t id = 0;
    int64_t t_us = 0;
    uint8_t repeat = 0;
};

PendingShot pendingShots[8];

// Statystyki
uint32_t imuSamples = 0;
uint32_t imuSkipped = 0;
uint32_t i2cErrors = 0;
uint32_t rawTriggerEdges = 0;
uint32_t shotsAccepted = 0;
uint32_t edgesIgnored = 0;
uint32_t txOk = 0;
uint32_t txFailed = 0;

unsigned long lastStatus = 0;
unsigned long lastReconnect = 0;
bool wasWifiConnected = false;

// =====================================
// Przerwania
// =====================================

void IRAM_ATTR onImuReady() {
    int64_t timestamp = esp_timer_get_time();
    BaseType_t wake = pdFALSE;

    if (xQueueSendFromISR(
            imuQueue, &timestamp, &wake) != pdTRUE) {
        imuQueueDrops++;
    }

    if (wake) portYIELD_FROM_ISR();
}

void IRAM_ATTR onTriggerRise() {
    int64_t timestamp = esp_timer_get_time();
    BaseType_t wake = pdFALSE;

    if (xQueueSendFromISR(
            triggerQueue, &timestamp, &wake) != pdTRUE) {
        triggerQueueDrops++;
    }

    if (wake) portYIELD_FROM_ISR();
}

// =====================================
// MPU-6050
// =====================================

bool writeReg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.write(value);

    return Wire.endTransmission() == 0;
}

uint8_t readReg(uint8_t reg) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);

    if (Wire.endTransmission(false) != 0) {
        return 0xFF;
    }

    if (Wire.requestFrom(MPU_ADDR, (uint8_t)1) != 1) {
        return 0xFF;
    }

    return Wire.read();
}

int16_t toInt16(uint8_t high, uint8_t low) {
    return (int16_t)(((uint16_t)high << 8) | low);
}

bool readImu(ImuSample &sample) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(REG_ACCEL_XOUT_H);

    if (Wire.endTransmission(false) != 0) {
        return false;
    }

    if (Wire.requestFrom(MPU_ADDR, (uint8_t)14) != 14) {
        return false;
    }

    uint8_t data[14];

    for (int i = 0; i < 14; i++) {
        data[i] = Wire.read();
    }

    sample.ax = toInt16(data[0], data[1]);
    sample.ay = toInt16(data[2], data[3]);
    sample.az = toInt16(data[4], data[5]);

    // Bajty 6-7: temperatura (niewysylana)

    sample.gx = toInt16(data[8], data[9]);
    sample.gy = toInt16(data[10], data[11]);
    sample.gz = toInt16(data[12], data[13]);

    readReg(REG_INT_STATUS);
    return true;
}

bool initMpu() {
    Wire.begin(PIN_SDA, PIN_SCL, 400000);
    Wire.setTimeOut(20);

    uint8_t id = readReg(REG_WHO_AM_I);
    Serial.printf("WHO_AM_I: 0x%02X\n", id);

    if (id != 0x68 && id != 0x72) {
        return false;
    }

    bool ok = writeReg(REG_INT_ENABLE, 0x00);

    ok &= writeReg(REG_PWR_MGMT_1, 0x01);
    ok &= writeReg(REG_PWR_MGMT_2, 0x00);
    delay(100);

    ok &= writeReg(REG_CONFIG, 0x03);
    ok &= writeReg(REG_SMPLRT_DIV, 9);
    ok &= writeReg(REG_GYRO_CONFIG, 0x00);
    ok &= writeReg(REG_ACCEL_CONFIG, 0x00);
    ok &= writeReg(REG_INT_PIN_CFG, 0x00);

    readReg(REG_INT_STATUS);
    return ok;
}

// =====================================
// Wi-Fi i UDP
// =====================================

void startWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    lastReconnect = millis();
    Serial.println("[WIFI] Laczenie...");
}

void updateWifi() {
    bool connected = WiFi.status() == WL_CONNECTED;

    if (connected && !wasWifiConnected) {
        WiFi.setSleep(false);

        Serial.print("[WIFI] Connected, IP: ");
        Serial.println(WiFi.localIP());

        Serial.print("[UDP] Destination: ");
        Serial.print(LAPTOP_IP);
        Serial.printf(":%u\n", LAPTOP_PORT);
    }

    if (!connected && wasWifiConnected) {
        Serial.println("[WIFI] Disconnected");
    }

    if (!connected && millis() - lastReconnect >= 5000) {
        WiFi.reconnect();
        lastReconnect = millis();
    }

    wasWifiConnected = connected;
}

PacketHeader makeHeader(uint8_t type) {
    PacketHeader header = {};

    header.magic = MAGIC;
    header.version = VERSION;
    header.type = type;
    header.seq = sequenceNumber++;
    header.t_send = esp_timer_get_time();

    return header;
}

bool sendPacket(const void *data, size_t size) {
    if (WiFi.status() != WL_CONNECTED) {
        txFailed++;
        return false;
    }

    if (!udp.beginPacket(LAPTOP_IP, LAPTOP_PORT)) {
        txFailed++;
        return false;
    }

    size_t written = udp.write(
        reinterpret_cast<const uint8_t *>(data), size
    );

    bool ok = written == size && udp.endPacket() == 1;

    if (ok) {
        txOk++;
    } else {
        txFailed++;
    }

    return ok;
}

// =====================================
// Pakiety IMU
// =====================================

void flushImu() {
    if (imuCount == 0) return;

    imuPacket.header = makeHeader(TYPE_IMU);
    imuPacket.count = imuCount;

    // range 0: ACC +/-2g, GYRO +/-250 deg/s
    imuPacket.range = 0;
    imuPacket.reserved = 0;

    size_t size = sizeof(PacketHeader) + 4 +
                  imuCount * sizeof(ImuSample);

    sendPacket(&imuPacket, size);

    imuCount = 0;
}

void processImu() {
    int64_t timestamp;

    if (xQueueReceive(imuQueue, &timestamp, 0) != pdTRUE) {
        return;
    }

    // W przypadku zaleglosci bierzemy najnowsze DATA_RDY.
    int64_t newer;

    while (xQueueReceive(imuQueue, &newer, 0) == pdTRUE) {
        timestamp = newer;
        imuSkipped++;
    }

    ImuSample sample = {};
    sample.t_us = timestamp;

    if (!readImu(sample)) {
        i2cErrors++;
        return;
    }

    imuPacket.data[imuCount++] = sample;
    imuSamples++;

    if (imuCount == IMU_BATCH_SIZE) {
        flushImu();
    }
}

// =====================================
// Pakiety SHOT
// =====================================

void processTrigger() {
    int64_t timestamp;

    while (xQueueReceive(
               triggerQueue, &timestamp, 0) == pdTRUE) {

        rawTriggerEdges++;

        bool accept =
            lastAcceptedShotUs < 0 ||
            timestamp - lastAcceptedShotUs >= DEBOUNCE_US;

        if (!accept) {
            edgesIgnored++;
            continue;
        }

        lastAcceptedShotUs = timestamp;
        uint32_t id = ++nextShotId;
        shotsAccepted++;

        Serial.printf(
            "[SHOT] id=%lu t=%lld us\n",
            (unsigned long)id,
            (long long)timestamp
        );

        // Zapisujemy zdarzenie do potrojnej transmisji
        bool stored = false;

        for (auto &shot : pendingShots) {
            if (!shot.active) {
                shot.active = true;
                shot.id = id;
                shot.t_us = timestamp;
                shot.repeat = 0;
                stored = true;
                break;
            }
        }

        if (!stored) {
            txFailed++;
            Serial.println("[ERROR] SHOT queue full");
        }
    }
}

void sendPendingShots() {
    int64_t now = esp_timer_get_time();

    for (auto &shot : pendingShots) {
        if (!shot.active) continue;

        int64_t due = shot.t_us +
                      (int64_t)shot.repeat * SHOT_REPEAT_US;

        if (now < due) continue;

        ShotPacket packet = {};
        packet.header = makeHeader(TYPE_SHOT);
        packet.shot_id = shot.id;
        packet.t_shot_us = shot.t_us;
        packet.repeat = shot.repeat;

        sendPacket(&packet, sizeof(packet));

        shot.repeat++;

        if (shot.repeat >= 3) {
            shot.active = false;
        }
    }
}

// =====================================
// STATUS i diagnostyka
// =====================================

void sendStatus() {
    StatusPacket packet = {};

    packet.header = makeHeader(TYPE_STATUS);

    // Brak pomiaru napiecia baterii na tym etapie
    packet.battery_mv = 0;

    packet.rssi_dbm =
        WiFi.status() == WL_CONNECTED
        ? (int8_t)WiFi.RSSI()
        : 0;

    // Bit 0: polaczenie Wi-Fi
    packet.flags =
        WiFi.status() == WL_CONNECTED ? 1 : 0;

    packet.imu_overruns =
        imuQueueDrops + imuSkipped;

    sendPacket(&packet, sizeof(packet));
}

void printStatus() {
    Serial.println("=== STATUS 1s ===");

    Serial.printf(
        "IMU: %lu samples | I2C errors: %lu\n",
        (unsigned long)imuSamples,
        (unsigned long)i2cErrors
    );

    Serial.printf(
        "Skipped: %lu | IRQ drops: %lu\n",
        (unsigned long)imuSkipped,
        (unsigned long)imuQueueDrops
    );

    Serial.printf(
        "Trigger edges: %lu | shots: %lu | ignored: %lu\n",
        (unsigned long)rawTriggerEdges,
        (unsigned long)shotsAccepted,
        (unsigned long)edgesIgnored
    );

    Serial.printf(
        "UDP TX OK: %lu | failed: %lu | seq: %lu\n",
        (unsigned long)txOk,
        (unsigned long)txFailed,
        (unsigned long)sequenceNumber
    );

    imuSamples = 0;
    i2cErrors = 0;
    rawTriggerEdges = 0;
    shotsAccepted = 0;
    edgesIgnored = 0;
    txOk = 0;
    txFailed = 0;
}

// =====================================
// Setup / Loop
// =====================================

void setup() {
    Serial.begin(115200);
    delay(2000);

    Serial.println("=== SHOOTING TRAINER ESP32 ===");

    imuQueue = xQueueCreate(32, sizeof(int64_t));
    triggerQueue = xQueueCreate(64, sizeof(int64_t));

    if (!imuQueue || !triggerQueue) {
        Serial.println("[ERROR] Queue allocation failed");
        while (true) delay(1000);
    }

    pinMode(PIN_IMU_INT, INPUT);
    pinMode(PIN_TRIGGER, INPUT);

    if (!initMpu()) {
        Serial.println("[ERROR] MPU initialization failed");
        while (true) delay(1000);
    }

    attachInterrupt(
        digitalPinToInterrupt(PIN_IMU_INT),
        onImuReady,
        RISING
    );

    attachInterrupt(
        digitalPinToInterrupt(PIN_TRIGGER),
        onTriggerRise,
        RISING
    );

    if (!writeReg(REG_INT_ENABLE, 0x01)) {
        Serial.println("[ERROR] DATA_RDY enable failed");
        while (true) delay(1000);
    }

    startWifi();
    lastStatus = millis();

    Serial.println("[OK] Acquisition started");
}

void loop() {
    // Najpierw akwizycja, potem transmisja
    processTrigger();
    processImu();

    updateWifi();
    sendPendingShots();

    if (millis() - lastStatus >= 1000) {
        sendStatus();
        printStatus();
        lastStatus = millis();
    }

    delay(1);
}
