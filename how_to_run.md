# Smart Farm - How to Run

## Quick Start

### 1. Setup Virtual Environment (Recommended)
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the Application
```bash
# Make sure virtual environment is activated, then:
python app.py
```

### 3. Override COM port
```bash
python app.py --port COM13
```

### 4. List ports and select
```bash
python app.py --list-ports
```

### 5. Edit configuration
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
- Virtual environment (recommended)
- Required packages: `pip install -r requirements.txt`
- ESP32 with serial connection

## Virtual Environment Benefits
- Isolated dependencies
- No system-wide package conflicts
- Easy reproduction of environment
- Better security and stability