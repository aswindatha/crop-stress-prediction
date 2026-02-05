#include <ArduinoJson.h>
#include <HardwareSerial.h>

// Configuration
#define RELAY_MOTOR  25
#define RELAY_LIGHT  26
#define BAUD        115200

// Global variables
unsigned long motorOnAt = 0;
unsigned long lightOnAt = 0;

// Device configuration
struct DeviceConfig {
  int motor_gpio;
  int light_gpio;
  bool motor_active_low;
  bool light_active_low;
  int baud_rate;
};

DeviceConfig config;

void loadConfig() {
  // Default configuration
  config.motor_gpio = RELAY_MOTOR;
  config.light_gpio = RELAY_LIGHT;
  config.motor_active_low = true;
  config.light_active_low = true;
  config.baud_rate = BAUD;
  
  Serial.println("📝 Using default ESP32 configuration");
}

void sendRuntime(const char* device, unsigned long runtimeMs) {
  Serial.print("{\"device\":\"");
  Serial.print(device);
  Serial.print("\",\"runtime\":");
  Serial.print(runtimeMs / 1000);
  Serial.println("}");
}

void setMotor(bool on) {
  Serial.print("⚙️ setMotor(");
  Serial.print(on ? "true" : "false");
  Serial.println(")");
  
  if (on) {
    if (motorOnAt == 0) motorOnAt = millis();
    digitalWrite(config.motor_gpio, config.motor_active_low ? LOW : HIGH);
    Serial.print("🔌 MOTOR GPIO ");
    Serial.print(config.motor_gpio);
    Serial.print(" = ");
    Serial.println(config.motor_active_low ? "LOW (ON)" : "HIGH (ON)");
  } else {
    if (motorOnAt != 0) {
      sendRuntime("motor", millis() - motorOnAt);
      motorOnAt = 0;
    }
    digitalWrite(config.motor_gpio, config.motor_active_low ? HIGH : LOW);
    Serial.print("🔌 MOTOR GPIO ");
    Serial.print(config.motor_gpio);
    Serial.print(" = ");
    Serial.println(config.motor_active_low ? "HIGH (OFF)" : "LOW (OFF)");
  }
}

void setLight(bool on) {
  Serial.print("💡 setLight(");
  Serial.print(on ? "true" : "false");
  Serial.println(")");
  
  if (on) {
    if (lightOnAt == 0) lightOnAt = millis();
    digitalWrite(config.light_gpio, config.light_active_low ? LOW : HIGH);
    Serial.print("🔌 LIGHT GPIO ");
    Serial.print(config.light_gpio);
    Serial.print(" = ");
    Serial.println(config.light_active_low ? "LOW (ON)" : "HIGH (ON)");
  } else {
    if (lightOnAt != 0) {
      sendRuntime("light", millis() - lightOnAt);
      lightOnAt = 0;
    }
    digitalWrite(config.light_gpio, config.light_active_low ? HIGH : LOW);
    Serial.print("🔌 LIGHT GPIO ");
    Serial.print(config.light_gpio);
    Serial.print(" = ");
    Serial.println(config.light_active_low ? "HIGH (OFF)" : "LOW (OFF)");
  }
}

void processCommand(const char* cmd) {
  Serial.print("📥 Received command: ");
  Serial.println(cmd);
  
  if (strcmp(cmd, "MOTOR_ON") == 0) {
    Serial.println("🔧 Turning MOTOR ON");
    setMotor(true);
  }
  else if (strcmp(cmd, "MOTOR_OFF") == 0) {
    Serial.println("🔧 Turning MOTOR OFF");
    setMotor(false);
  }
  else if (strcmp(cmd, "LIGHT_ON") == 0) {
    Serial.println("🔧 Turning LIGHT ON");
    setLight(true);
  }
  else if (strcmp(cmd, "LIGHT_OFF") == 0) {
    Serial.println("🔧 Turning LIGHT OFF");
    setLight(false);
  }
  else {
    Serial.println("❌ Unknown command");
  }
}

void setup() {
  // Load configuration
  loadConfig();
  
  // Initialize pins
  pinMode(config.motor_gpio, OUTPUT);
  pinMode(config.light_gpio, OUTPUT);
  
  // Set initial state (OFF for Active LOW relays)
  digitalWrite(config.motor_gpio, config.motor_active_low ? HIGH : LOW);
  digitalWrite(config.light_gpio, config.light_active_low ? HIGH : LOW);
  
  Serial.begin(config.baud_rate);
  
  Serial.println("🚀 Smart Farm ESP32 Started");
  Serial.print("⚙️ Motor GPIO: ");
  Serial.println(config.motor_gpio);
  Serial.print("💡 Light GPIO: ");
  Serial.println(config.light_gpio);
  Serial.print("🔌 Active LOW: ");
  Serial.println(config.motor_active_low && config.light_active_low ? "Yes" : "No");
  Serial.print("📡 Baud Rate: ");
  Serial.println(config.baud_rate);
}

static char serialBuf[32];
uint8_t serialIdx = 0;

void loop() {
  // Handle serial commands (one line at a time)
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialIdx > 0) {
        serialBuf[serialIdx] = '\0';
        processCommand(serialBuf);
        serialIdx = 0;
      }
    } else if (serialIdx < sizeof(serialBuf) - 1) {
      serialBuf[serialIdx++] = c;
    }
  }
  delay(10);
}
