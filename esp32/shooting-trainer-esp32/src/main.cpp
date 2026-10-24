#include <Arduino.h>
#include <WiFi.h>

#include "wifi_credentials.h"

// Konfiguracja ponawiania polaczenia
const unsigned long RECONNECT_INTERVAL = 15000;

unsigned long lastReconnectAttempt = 0;
bool wasConnected = false;

void setup() {
    Serial.begin(115200);
    delay(2000);

    Serial.println();
    Serial.println("=== Shooting Trainer ESP32-C3 ===");

    // Tryb klienta Wi-Fi
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);

    // Informacje o urzadzeniu
    Serial.print("MAC: ");
    Serial.println(WiFi.macAddress());

    // Rozpoczecie laczenia
    Serial.print("Laczenie z: ");
    Serial.println(WIFI_SSID);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastReconnectAttempt = millis();
}

void loop() {
    bool connected = WiFi.status() == WL_CONNECTED;

    // Nowe polaczenie
    if (connected && !wasConnected) {
        Serial.println();
        Serial.println("[OK] Polaczono z Wi-Fi!");

        Serial.print("SSID: ");
        Serial.println(WiFi.SSID());

        Serial.print("IP: ");
        Serial.println(WiFi.localIP());

        Serial.print("Brama: ");
        Serial.println(WiFi.gatewayIP());

        Serial.print("MAC: ");
        Serial.println(WiFi.macAddress());

        Serial.print("RSSI: ");
        Serial.print(WiFi.RSSI());
        Serial.println(" dBm");
    }

    // Utrata polaczenia
    if (!connected && wasConnected) {
        Serial.println("[ERROR] Utracono Wi-Fi!");
    }

    // Ponawianie polaczenia co 15 sekund
    if (!connected &&
        millis() - lastReconnectAttempt >= RECONNECT_INTERVAL) {

        Serial.println("[INFO] Ponawianie polaczenia...");
        WiFi.reconnect();

        lastReconnectAttempt = millis();
    }

    wasConnected = connected;

     // Diagnostyka Wi-Fi co 5 sekund
    static unsigned long lastStatusCheck = 0;

    if (millis() - lastStatusCheck >= 5000) {
        lastStatusCheck = millis();

        Serial.print("[STATUS] Wi-Fi: ");

        if (WiFi.status() == WL_CONNECTED) {
            Serial.print("POLACZONO | IP: ");
            Serial.print(WiFi.localIP());

            Serial.print(" | RSSI: ");
            Serial.print(WiFi.RSSI());
            Serial.println(" dBm");
        } else {
            Serial.println("ROZLACZONO");
        }
    }
    
    delay(250);
}