// Standalone hardware diagnostic: no Wi-Fi, MQTT, or card writes.
// RC522: 3V3, GND, SS/SDA=5, RST=4, SCK=18, MISO=19, MOSI=23.
#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>

MFRC522 reader(5, 4);
unsigned long lastStatus = 0;

void printStatus() {
  reader.PCD_DumpVersionToSerial();
  byte version = reader.PCD_ReadRegister(MFRC522::VersionReg);
  if (version == 0x00 || version == 0xFF) {
    Serial.println("ERROR: no valid RC522 SPI response. Check connections, power, and reader hardware.");
  } else {
    Serial.println("Present ONE card or fob. Remove it before scanning it again.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nRC522 standalone diagnostic (no MQTT required)");
  SPI.begin(18, 19, 23, 5);
  reader.PCD_Init();
  delay(4);
  printStatus();
  lastStatus = millis();
}

void loop() {
  if (millis() - lastStatus >= 5000) {
    printStatus();
    lastStatus = millis();
  }
  if (!reader.PICC_IsNewCardPresent()) {
    delay(20);
    return;
  }
  if (!reader.PICC_ReadCardSerial()) {
    Serial.println("Card detected, but UID read failed. Hold one tag steady near the antenna.");
    delay(100);
    return;
  }
  Serial.print("UID: ");
  for (byte i = 0; i < reader.uid.size; ++i) {
    if (reader.uid.uidByte[i] < 0x10) Serial.print('0');
    Serial.print(reader.uid.uidByte[i], HEX);
  }
  Serial.println();
  reader.PICC_HaltA();
  reader.PCD_StopCrypto1();
}
