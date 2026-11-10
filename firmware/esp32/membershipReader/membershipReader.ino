// Dedicated RC522 membership reader. Never publishes refrigerator/product data.
#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <esp_system.h>
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

MFRC522 rfid(5, 4);  // SS GPIO5, RST GPIO4; SPI SCK18 MISO19 MOSI23
WiFiClient network;
PubSubClient mqtt(network);
String epoch, operation, lastOperation, purpose;
unsigned long armedAt = 0, absentSince = 0, nextConnect = 0, heartbeatAt = 0, lastRead = 0;
bool fresh = false;
time_t operationExpires = 0;

String randomId() {
  char id[33];
  snprintf(id, sizeof(id), "%08lx%08lx%08lx%08lx", (unsigned long)esp_random(),
           (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random());
  return String(id);
}

void clearArm() { operation = ""; purpose = ""; fresh = false; absentSince = 0; }

void status(bool online) {
  JsonDocument doc;
  doc["v"] = 1; doc["online"] = online; doc["reader_epoch"] = epoch;
  String payload; serializeJson(doc, payload);
  mqtt.publish(MEMBERSHIP_TOPIC "/status", payload.c_str(), false);
}

void command(char* topic, byte* payload, unsigned int length) {
  if (String(topic) != MEMBERSHIP_TOPIC "/command" || length > 512) return;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length)) return;
  if (doc["v"].as<int>() != 1 || doc["reader_epoch"].as<String>() != epoch) return;
  String id = doc["operation_id"].as<String>();
  if (id.length() != 32) return;
  String action = doc["action"].as<String>();
  if (action == "cancel") { if (id == operation) clearArm(); return; }
  time_t now = time(nullptr);
  long long expires = doc["expires_at"].as<long long>();
  String requestedPurpose = doc["purpose"].as<String>();
  if (action != "arm" || id == lastOperation || operation.length() || now < 1700000000 ||
      expires <= now || expires > now + 65 ||
      (requestedPurpose != "enroll" && requestedPurpose != "checkout")) return;
  operation = id; lastOperation = id; purpose = requestedPurpose; armedAt = millis(); operationExpires = expires;
  fresh = false; absentSince = 0;
  Serial.println("Armed: remove any card, then present a card.");
}

void setup() {
  Serial.begin(115200);
  SPI.begin(18, 19, 23, 5);
  rfid.PCD_Init();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, NTP_HOST);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(command);
  mqtt.setBufferSize(1024);
  mqtt.setSocketTimeout(2);
  mqtt.setKeepAlive(10);
}

void loop() {
  unsigned long now = millis();
  if (WiFi.status() != WL_CONNECTED) { clearArm(); return; }
  if (!mqtt.connected()) {
    clearArm();
    if ((long)(now - nextConnect) < 0) return;
    nextConnect = now + 3000;
    epoch = randomId(); lastOperation = "";
    JsonDocument will;
    will["v"] = 1; will["online"] = false; will["reader_epoch"] = epoch;
    String payload; serializeJson(will, payload);
    String clientId = "membership-" + String((unsigned long)ESP.getEfuseMac(), HEX);
    if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD,
                     MEMBERSHIP_TOPIC "/status", 0, false, payload.c_str(), true)) {
      mqtt.subscribe(MEMBERSHIP_TOPIC "/command", 1);
      status(true); heartbeatAt = now;
    }
    return;
  }
  mqtt.loop();
  if (now - heartbeatAt >= 5000) { status(true); heartbeatAt = now; }
  if (!operation.length()) return;
  if (now - armedAt >= 60000 || time(nullptr) >= operationExpires) { clearArm(); return; }
  if (now - lastRead < 80) return;
  lastRead = now;
  if (!fresh) {
    // WUPA sees halted cards too: a card already present at arm cannot count.
    byte answer[2]; byte size = sizeof(answer);
    MFRC522::StatusCode result = rfid.PICC_WakeupA(answer, &size);
    if (result == MFRC522::STATUS_TIMEOUT) {
      if (!absentSince) absentSince = now;
      if (now - absentSince >= 300) fresh = true;
    } else {
      absentSince = 0;
      if (rfid.PICC_ReadCardSerial()) rfid.PICC_HaltA();
    }
    return;
  }
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  if (rfid.uid.size != 4 && rfid.uid.size != 7 && rfid.uid.size != 10) {
    rfid.PICC_HaltA(); return;
  }
  String uid;
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 16) uid += '0';
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  JsonDocument event;
  event["v"] = 1; event["operation_id"] = operation;
  event["event_id"] = randomId(); event["reader_epoch"] = epoch; event["uid"] = uid;
  String payload; serializeJson(event, payload);
  mqtt.publish(MEMBERSHIP_TOPIC "/event", payload.c_str(), false);
  Serial.println("UID: " + uid);
  rfid.PICC_HaltA(); rfid.PCD_StopCrypto1(); clearArm();
}
