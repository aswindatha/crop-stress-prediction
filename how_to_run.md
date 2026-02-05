# Smart Farm - How to Run

## Quick Start

### 1. Use configuration file
```bash
python app.py
```

### 2. Override COM port
```bash
python app.py --port COM13
```

### 3. List ports and select
```bash
python app.py
```

### 4. Edit configuration
```bash
nano config.json
```

## Features

### QR Code Access
- **Press 'q'** in terminal to display QR code and URL
- Scan QR code with mobile device to access Smart Farm
- QR code contains your local IP address and port

### Configuration
All settings are in `config.json`:
- Serial port settings
- Device names and GPIO pins
- Power and flow rate calculations
- ML model parameters
- UI settings

### Time-Based Calculations
- **Water**: `(runtime_seconds / 60) * flow_rate_l_per_min`
- **Power**: `(runtime_seconds / 3600) * power_watt / 1000`

## Commands
```bash
# List available ports
python app.py --list-ports

# Use specific port
python app.py --port COM13

# Interactive selection
python app.py

# Show QR code (press 'q' when running)
# QR code displays local IP and port for mobile access
```

## Mobile Access
1. Start the application
2. Press 'q' in terminal
3. Scan QR code with phone
4. Access Smart Farm from mobile device

## Requirements
- Python 3.11+
- Required packages: `pip install keyboard qrcode-terminal`
- ESP32 with serial connection