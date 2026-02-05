# Smart Farm — Arduino / ESP32 Setup

## Board
- **Board:** ESP32 Dev Module
- **Upload Speed:** 115200
- **CPU Frequency:** 240MHz (WiFi/BT)
- **Flash Size:** 4MB

## Libraries
- **ArduinoJson** (v6.x) — install via Library Manager

## Pin Mapping
| Function | GPIO | Notes        |
|----------|------|--------------|
| Relay 1  | 25   | Motor / Pump (Active LOW) |
| Relay 2  | 26   | Grow Light (Active LOW) |

## Relay Configuration
- **Type:** Active LOW relays
- **Logic:** LOW = ON, HIGH = OFF
- **Initial State:** HIGH (relays OFF on startup)

## Serial
- **Baud rate:** 115200
- **USB Serial** — connect to laptop for commands and runtime reports

## Wiring
- Relay modules: IN pin → GPIO 25 / 26; VCC → 3.3V or 5V per module; GND → GND
- Relay COM/NO/NC to motor and light as needed
