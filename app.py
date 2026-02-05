"""
Smart Farm — Backend + ML + API + Web Server
Serial ↔ ESP32 | SQLite | Virtual sensors | Flask UI
"""

import os
import json
import socket
import sqlite3
import sys
import threading
import time
import argparse
import keyboard
from datetime import datetime, timedelta
from contextlib import contextmanager

from flask import Flask, render_template, request, jsonify
import serial
import serial.tools.list_ports
import warnings

# Suppress sklearn warnings
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn.utils.validation")

# Suppress Flask access logs
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Load configuration
def load_config():
    """Load configuration from config.json file."""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Config file not found: {config_path}")
        print("📝 Creating default config file...")
        create_default_config()
        return load_config()
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing config.json: {e}")
        sys.exit(1)

def create_default_config():
    """Create default configuration file."""
    default_config = {
        "serial": {
            "com_port": "COM13",
            "baud_rate": 115200,
            "timeout": 0.1,
            "auto_detect": True
        },
        "devices": {
            "motor": {
                "name": "Bore Pump",
                "gpio": 25,
                "active_low": True,
                "flow_rate_l_per_min": 20.0,
                "power_watt": 750.0
            },
            "light": {
                "name": "Grow Light",
                "gpio": 26,
                "active_low": True,
                "power_watt": 100.0
            }
        },
        "ml": {
            "ideal_moisture": 0.65,
            "stage_weights": {
                "seedling": 1.2,
                "vegetative": 1.0,
                "flowering": 1.1,
                "fruiting": 1.15
            }
        },
        "ui": {
            "poll_interval_ms": 2000,
            "host": "0.0.0.0",
            "port": 5000
        }
    }
    
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
    print(f"✅ Default config created: {config_path}")

def parse_arguments():
    """Parse command line arguments for COM port selection."""
    parser = argparse.ArgumentParser(description='Smart Farm Server')
    parser.add_argument('--port', '-p', type=str, 
                       help='Specify COM port (e.g., COM13, /dev/ttyUSB0)')
    parser.add_argument('--list-ports', '-l', action='store_true',
                       help='List available COM ports and exit')
    return parser.parse_args()

def list_com_ports():
    """List all available COM ports."""
    print("🔍 Available COM ports:")
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("  ❌ No serial ports found")
        return
    
    for i, port in enumerate(ports, 1):
        print(f"  {i}. {port.device} - {port.description}")
    
    esp_ports = [p for p in ports if any(keyword in p.description 
                for keyword in ["USB", "Serial", "CP210", "CH340", "Silicon Labs"])]
    
    if esp_ports:
        print("\n✅ Potential ESP32 ports:")
        for port in esp_ports:
            print(f"  🎯 {port.device} - {port.description}")

# Parse arguments before loading config
args = parse_arguments()

# Load configuration
config = load_config()

# Override config with command line arguments
if args.port:
    config["serial"]["com_port"] = args.port
    print(f"🔧 Using command-line COM port: {args.port}")

if args.list_ports:
    list_com_ports()
    sys.exit(0)

# ML Models - Required
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "model"))
try:
    from prediction_functions import SmartFarmPredictor
    MODEL_PATH = os.path.join(os.path.dirname(__file__), "model")
    ml_predictor = SmartFarmPredictor(MODEL_PATH)
    HAS_ML_MODELS = True
except Exception as e:
    print(f"Error loading ML models: {e}")
    HAS_ML_MODELS = False
    ml_predictor = None
    sys.exit(1)  # Exit if models cannot be loaded - no fallback

# --- Config-based Constants ---
DB_PATH = os.path.join(os.path.dirname(__file__), "farm.db")
SERIAL_BAUD = config["serial"]["baud_rate"]
SERIAL_TIMEOUT = config["serial"]["timeout"]
FLOW_RATE_L_PER_MIN = config["devices"]["motor"]["flow_rate_l_per_min"]
MOTOR_WATT = config["devices"]["motor"]["power_watt"]
LIGHT_WATT = config["devices"]["light"]["power_watt"]
IDEAL_MOISTURE = config["ml"]["ideal_moisture"]
STAGE_WEIGHTS = config["ml"]["stage_weights"]

app = Flask(__name__)
serial_port = None
serial_lock = threading.Lock()
# In-memory relay state (we control it via serial)
relay_state = {"motor": False, "light": False}
# Last runtime received (for immediate UI update)
last_runtimes = {"motor": 0, "light": 0}
# Track when relays were turned ON (for real-time analytics)
relay_start_times = {"motor": None, "light": None}


# --- Database ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                time TEXT,
                device TEXT,
                runtime_sec INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Default settings
        for key, value in [
            ("motor_name", "Bore Pump"),
            ("light_name", "Grow Light"),
            ("crop", "tomato"),
            ("stage", "flowering"),
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def log_usage(device: str, runtime_sec: int):
    with db() as conn:
        conn.execute(
            "INSERT INTO usage (time, device, runtime_sec) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), device, runtime_sec),
        )


def get_setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )


def get_recent_usage(hours: int = 24):
    with db() as conn:
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            "SELECT time, device, runtime_sec FROM usage WHERE time >= ? ORDER BY time DESC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_usage_for_ml(days: int = 30):
    """Return list of (runtime_sec, day_offset) for pump for ML."""
    with db() as conn:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            "SELECT time, device, runtime_sec FROM usage WHERE time >= ? AND device = 'motor'",
            (since,),
        ).fetchall()
        return [(r["runtime_sec"], r["time"]) for r in rows]


# --- Serial ---
def find_esp32_port():
    # Check for manual override first
    manual_port = os.getenv("ESP32_COM_PORT")
    if manual_port:
        print(f"🔧 Using manual COM port override: {manual_port}")
        return manual_port
    
    # Use config port if auto-detect is disabled
    if not config["serial"]["auto_detect"]:
        config_port = config["serial"]["com_port"]
        print(f"🔧 Using configured COM port: {config_port}")
        return config_port
    
    # Get all available ports
    available_ports = serial.tools.list_ports.comports()
    if not available_ports:
        print("❌ No serial ports found")
        return None
    
    print("\n🔍 Available COM ports:")
    for i, port in enumerate(available_ports, 1):
        print(f"  {i}. {port.device} - {port.description}")
    
    # Try to auto-detect ESP32
    esp_ports = []
    for port in available_ports:
        if "USB" in port.description or "Serial" in port.description or "CP210" in port.description or "CH340" in port.description or "Silicon Labs" in port.description:
            esp_ports.append(port)
    
    if esp_ports:
        print(f"\n✅ Found {len(esp_ports)} potential ESP32 port(s):")
        for i, port in enumerate(esp_ports, 1):
            print(f"  {i}. {port.device} - {port.description}")
        
        # If only one ESP32 port found, use it
        if len(esp_ports) == 1:
            selected_port = esp_ports[0].device
            print(f"\n🎯 Auto-selected: {selected_port}")
            return selected_port
        
        # If multiple ESP32 ports, let user choose
        while True:
            try:
                choice = input(f"\n📝 Select ESP32 port (1-{len(esp_ports)}) or press Enter to scan all: ").strip()
                if not choice:
                    break
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(esp_ports):
                    selected_port = esp_ports[choice_idx].device
                    print(f"🎯 Selected: {selected_port}")
                    return selected_port
                else:
                    print("❌ Invalid selection. Try again.")
            except ValueError:
                print("❌ Please enter a number.")
    
    # If no ESP32 ports found or user wants to see all ports
    print("\n📝 Please select COM port manually:")
    for i, port in enumerate(available_ports, 1):
        print(f"  {i}. {port.device} - {port.description}")
    
    while True:
        try:
            choice = input(f"\n📝 Select COM port (1-{len(available_ports)}): ").strip()
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(available_ports):
                selected_port = available_ports[choice_idx].device
                print(f"🎯 Selected: {selected_port}")
                return selected_port
            else:
                print("❌ Invalid selection. Try again.")
        except ValueError:
            print("❌ Please enter a number.")
        except KeyboardInterrupt:
            print("\n👋 Exiting...")
            return None


def open_serial():
    global serial_port
    if serial_port and serial_port.is_open:
        return True
    port = find_esp32_port()
    if not port:
        print("❌ Cannot open serial: No ESP32 port found")
        return False
    try:
        print(f"🔌 Attempting to open serial port: {port}")
        serial_port = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        print(f"✅ Serial port opened successfully: {port}")
        return True
    except Exception as e:
        print(f"❌ Failed to open serial port {port}: {e}")
        return False


def send_command(cmd: str) -> bool:
    global serial_port  # Add global declaration here
    with serial_lock:
        if not open_serial():
            return False
        try:
            command_to_send = cmd.strip() + "\n"
            print(f"🔌 Sending command: {repr(command_to_send)}")
            serial_port.write(command_to_send.encode())
            serial_port.flush()
            print(f"✅ Command sent successfully: {cmd.strip()}")
            return True
        except Exception as e:
            print(f"❌ Failed to send command '{cmd}': {e}")
            serial_port = None
            return False


def serial_reader_thread():
    """Background: read lines from ESP32, parse JSON runtime, store in DB."""
    global serial_port  # so except block can set serial_port = None
    buffer = b""
    while True:
        try:
            if serial_port and serial_port.is_open:
                buffer += serial_port.read(serial_port.in_waiting or 1)
                while b"\n" in buffer or b"}" in buffer:
                    line = buffer.split(b"\n")[0].decode("utf-8", errors="ignore").strip()
                    if "}" in line:
                        line = line[: line.index("}") + 1]
                    buffer = buffer[buffer.find(b"\n") + 1:] if b"\n" in buffer else b""
                    if "device" in line and "runtime" in line:
                        try:
                            data = json.loads(line)
                            device = data.get("device", "")
                            runtime = int(data.get("runtime", 0))
                            if device in ("motor", "light") and runtime >= 0:
                                log_usage(device, runtime)
                                last_runtimes[device] = runtime
                        except json.JSONDecodeError:
                            pass
            else:
                open_serial()
        except Exception:
            serial_port = None
        time.sleep(0.05)


# --- Virtual sensors & ML ---
def virtual_moisture(pump_runtime_sec: float, temp_c: float = 24.0, rainfall_mm: float = 3.0) -> float:
    """ML-based soil moisture prediction using trained models."""
    crop = get_setting("crop", "tomato")
    stage = get_setting("stage", "flowering")
    
    if HAS_ML_MODELS:
        try:
            return ml_predictor.predict_soil_moisture(
                temperature_c=temp_c,
                humidity_percent=75.0,  # Good humidity
                rainfall_mm=rainfall_mm,
                light_hours=12.0,  # Good daylight
                pump_runtime_sec=pump_runtime_sec,
                crop=crop,
                stage=stage
            )
        except Exception as e:
            print(f"Error in ML moisture prediction: {e}")
            sys.exit(1)
    else:
        sys.exit(1)


def power_kwh(seconds: float, watt: float) -> float:
    return seconds * watt / 3600000.0


def water_liters(runtime_sec: float) -> float:
    return runtime_sec / 60.0 * FLOW_RATE_L_PER_MIN


def crop_stress_index(moisture: float, stage: str) -> float:
    """ML-based crop stress index prediction."""
    crop = get_setting("crop", "tomato")
    
    if HAS_ML_MODELS:
        try:
            return ml_predictor.predict_crop_stress(
                temperature_c=24.0,  # Optimal temperature
                humidity_percent=75.0,  # Good humidity
                rainfall_mm=3.0,  # Moderate rainfall
                light_hours=12.0,  # Good daylight
                pump_runtime_sec=1800,  # Default pump runtime
                soil_moisture=moisture,
                crop=crop,
                stage=stage
            )
        except Exception as e:
            print(f"Error in ML crop stress prediction: {e}")
            sys.exit(1)
    else:
        sys.exit(1)


def get_aggregates(hours: int = 24):
    """Sum motor/light runtimes in last N hours for virtual sensors.
    Includes both completed runtimes from DB and current active runtime."""
    rows = get_recent_usage(hours)
    motor_sec = sum(r["runtime_sec"] for r in rows if r["device"] == "motor")
    light_sec = sum(r["runtime_sec"] for r in rows if r["device"] == "light")
    
    # Add current active runtime if relay is ON
    current_time = datetime.utcnow().timestamp()
    if relay_state["motor"] and relay_start_times["motor"]:
        active_motor_sec = int(current_time - relay_start_times["motor"])
        motor_sec += active_motor_sec
    if relay_state["light"] and relay_start_times["light"]:
        active_light_sec = int(current_time - relay_start_times["light"])
        light_sec += active_light_sec
    
    return motor_sec, light_sec


def get_predictions():
    """ML-based predictions for next-day water and power usage."""
    motor_sec, light_sec = get_aggregates(24)
    crop = get_setting("crop", "tomato")
    stage = get_setting("stage", "flowering")
    
    if HAS_ML_MODELS:
        try:
            # Predict water usage with optimal parameters
            pred_water = ml_predictor.predict_water_usage(
                temperature_c=24.0,  # Optimal temperature
                humidity_percent=75.0,  # Good humidity
                rainfall_mm=3.0,  # Moderate rainfall
                light_hours=12.0,  # Good daylight
                soil_moisture=0.7,  # High moisture
                crop=crop,
                stage=stage
            )
            
            # Predict power usage
            pred_power = ml_predictor.predict_power_usage(
                temperature_c=24.0,  # Optimal temperature
                humidity_percent=75.0,  # Good humidity
                light_hours=12.0,  # Good daylight
                pump_runtime_sec=motor_sec,
                light_runtime_sec=light_sec,
                crop=crop,
                stage=stage
            )
            
            return {
                "water_liters": round(pred_water * 0.005, 1),  # Scale down significantly for demo
                "power_kwh": round(pred_power, 2),
            }
        except Exception as e:
            print(f"Error in ML predictions: {e}")
            sys.exit(1)
    else:
        sys.exit(1)


# --- API ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    motor_sec, light_sec = get_aggregates(24)
    # Realistic environmental data for healthy crops
    temp_c = 24.0  # Optimal temperature
    rainfall_mm = 3.0  # Moderate rainfall
    humidity_percent = 75.0  # Good humidity
    light_hours = 12.0  # Good daylight
    
    moisture = virtual_moisture(motor_sec, temp_c, rainfall_mm)
    stage = get_setting("stage", "flowering")
    csi = round(crop_stress_index(moisture, stage), 3)
    predictions = get_predictions()
    return jsonify({
        "relay": relay_state,
        "motor_name": config["devices"]["motor"]["name"],
        "light_name": config["devices"]["light"]["name"],
        "crop": get_setting("crop", "tomato"),
        "stage": stage,
        "last_runtimes": dict(last_runtimes),
        "virtual": {
            "soil_moisture": round(moisture, 3),
            "csi": csi,
            "water_liters_24h": round(water_liters(motor_sec), 1),
            "power_kwh_24h": round(
                power_kwh(motor_sec, MOTOR_WATT) + power_kwh(light_sec, LIGHT_WATT), 2
            ),
        },
        "predictions": predictions,
        "serial_connected": open_serial(),
    })


@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.get_json() or {}
    device = data.get("device")
    state = data.get("state")
    if device not in ("motor", "light"):
        return jsonify({"ok": False, "error": "Invalid device"}), 400
    cmd = f"{device.upper()}_{ 'ON' if state else 'OFF'}"
    ok = send_command(cmd)
    if ok:
        relay_state[device] = state
        # Track start time when turning ON
        if state:
            relay_start_times[device] = datetime.utcnow().timestamp()
        # Clear start time when turning OFF (runtime will be logged by ESP32)
        else:
            relay_start_times[device] = None
    return jsonify({"ok": ok, "relay": relay_state})


@app.route("/api/rename", methods=["POST"])
def api_rename():
    data = request.get_json() or {}
    motor_name = data.get("motor_name")
    light_name = data.get("light_name")
    if motor_name is not None:
        set_setting("motor_name", str(motor_name).strip() or "Bore Pump")
    if light_name is not None:
        set_setting("light_name", str(light_name).strip() or "Grow Light")
    return jsonify({"ok": True})


@app.route("/api/debug", methods=["GET"])
def api_debug():
    """Debug endpoint to print ESP32 data, model inputs, and outputs to terminal"""
    
    print("\n" + "="*80)
    print("🔍 SMART FARM DEBUG - DATA FLOW ANALYSIS")
    print("="*80)
    
    # Get current settings
    crop = get_setting("crop", "tomato")
    stage = get_setting("stage", "flowering")
    
    print(f"\n📋 CURRENT SETTINGS:")
    print(f"  Crop: {crop}")
    print(f"  Stage: {stage}")
    print(f"  Motor Name: {get_setting('motor_name', 'Bore Pump')}")
    print(f"  Light Name: {get_setting('light_name', 'Grow Light')}")
    
    # Get ESP32 data (recent usage and last runtimes)
    motor_sec, light_sec = get_aggregates(24)
    recent_usage = get_recent_usage(24)
    
    print(f"\n📡 ESP32 DATA RECEIVED:")
    print(f"  Motor runtime (24h): {motor_sec} seconds ({motor_sec/60:.1f} minutes)")
    print(f"  Light runtime (24h): {light_sec} seconds ({light_sec/60:.1f} minutes)")
    print(f"  Last motor runtime: {last_runtimes.get('motor', 0)} seconds")
    print(f"  Last light runtime: {last_runtimes.get('light', 0)} seconds")
    print(f"  Recent usage records: {len(recent_usage)} entries")
    
    # Show last 5 ESP32 messages
    if recent_usage:
        print(f"  Last 5 ESP32 messages:")
        for i, record in enumerate(recent_usage[:5]):
            print(f"    {i+1}. {record['time']} - {record['device']}: {record['runtime_sec']}s")
    
    # Environmental data (currently simulated)
    temp_c, rainfall_mm = 28.0, 0.0
    humidity_percent = 60.0
    light_hours = 12.0
    
    print(f"\n🌤️  ENVIRONMENTAL DATA:")
    print(f"  Temperature: {temp_c}°C")
    print(f"  Humidity: {humidity_percent}%")
    print(f"  Rainfall: {rainfall_mm} mm")
    print(f"  Light hours: {light_hours} hours")
    
    # Model inputs for each prediction
    print(f"\n🧠 ML MODEL INPUTS:")
    
    # Soil moisture model inputs
    moisture_inputs = {
        'temperature_c': temp_c,
        'humidity_percent': humidity_percent,
        'rainfall_mm': rainfall_mm,
        'light_hours': light_hours,
        'pump_runtime_sec': motor_sec,
        'crop': crop,
        'stage': stage
    }
    print(f"  🌱 Soil Moisture Model Inputs:")
    for key, value in moisture_inputs.items():
        print(f"    {key}: {value}")
    
    # Crop stress model inputs
    stress_inputs = {
        'temperature_c': temp_c,
        'humidity_percent': humidity_percent,
        'rainfall_mm': rainfall_mm,
        'light_hours': light_hours,
        'pump_runtime_sec': motor_sec,
        'soil_moisture': 0.0,  # Will be calculated
        'crop': crop,
        'stage': stage
    }
    print(f"  🌾 Crop Stress Model Inputs:")
    for key, value in stress_inputs.items():
        print(f"    {key}: {value}")
    
    # Water usage model inputs
    water_inputs = {
        'temperature_c': temp_c,
        'humidity_percent': humidity_percent,
        'rainfall_mm': rainfall_mm,
        'light_hours': light_hours,
        'soil_moisture': 0.0,  # Will be calculated
        'crop': crop,
        'stage': stage
    }
    print(f"  💧 Water Usage Model Inputs:")
    for key, value in water_inputs.items():
        print(f"    {key}: {value}")
    
    # Power usage model inputs
    power_inputs = {
        'temperature_c': temp_c,
        'humidity_percent': humidity_percent,
        'light_hours': light_hours,
        'pump_runtime_sec': motor_sec,
        'light_runtime_sec': light_sec,
        'crop': crop,
        'stage': stage
    }
    print(f"  ⚡ Power Usage Model Inputs:")
    for key, value in power_inputs.items():
        print(f"    {key}: {value}")
    
    # Execute models and capture outputs
    print(f"\n🎯 ML MODEL OUTPUTS:")
    
    try:
        # Soil moisture prediction
        moisture_output = ml_predictor.predict_soil_moisture(**moisture_inputs)
        print(f"  🌱 Soil Moisture: {moisture_output:.4f} (0-1 scale)")
        
        # Update stress and water inputs with actual moisture
        stress_inputs['soil_moisture'] = moisture_output
        water_inputs['soil_moisture'] = moisture_output
        
        # Crop stress prediction
        stress_output = ml_predictor.predict_crop_stress(**stress_inputs)
        print(f"  🌾 Crop Stress Index: {stress_output:.4f}")
        
        # Water usage prediction
        water_output = ml_predictor.predict_water_usage(**water_inputs)
        print(f"  💧 Water Usage: {water_output:.2f} liters")
        
        # Power usage prediction
        power_output = ml_predictor.predict_power_usage(**power_inputs)
        print(f"  ⚡ Power Usage: {power_output:.4f} kWh")
        
        # Yield prediction
        yield_inputs = {
            'temperature_c': temp_c,
            'humidity_percent': humidity_percent,
            'rainfall_mm': rainfall_mm,
            'light_hours': light_hours,
            'soil_moisture': moisture_output,
            'crop_stress_index': stress_output,
            'crop': crop,
            'stage': stage
        }
        yield_output = ml_predictor.predict_yield(**yield_inputs)
        print(f"  🌾 Yield Prediction: {yield_output:.2f} units")
        
        print(f"\n✅ All ML models executed successfully!")
        
    except Exception as e:
        print(f"\n❌ ERROR in ML model execution: {e}")
        import traceback
        traceback.print_exc()
    
    # Relay state
    print(f"\n🔌 RELAY STATES:")
    print(f"  Motor: {'ON' if relay_state.get('motor') else 'OFF'}")
    print(f"  Light: {'ON' if relay_state.get('light') else 'OFF'}")
    
    # Serial connection status
    print(f"\n🔗 CONNECTION STATUS:")
    print(f"  Serial Connected: {open_serial()}")
    print(f"  ESP32 Port: {find_esp32_port() or 'Not found'}")
    
    print("="*80)
    print("🔍 END DEBUG ANALYSIS")
    print("="*80 + "\n")
    
    # Return JSON response with all data
    return jsonify({
        "status": "debug_complete",
        "timestamp": datetime.utcnow().isoformat(),
        "esp32_data": {
            "motor_runtime_24h": motor_sec,
            "light_runtime_24h": light_sec,
            "last_motor_runtime": last_runtimes.get('motor', 0),
            "last_light_runtime": last_runtimes.get('light', 0),
            "recent_usage_count": len(recent_usage)
        },
        "environmental": {
            "temperature_c": temp_c,
            "humidity_percent": humidity_percent,
            "rainfall_mm": rainfall_mm,
            "light_hours": light_hours
        },
        "settings": {
            "crop": crop,
            "stage": stage
        },
        "model_outputs": {
            "soil_moisture": moisture_output if 'moisture_output' in locals() else None,
            "crop_stress_index": stress_output if 'stress_output' in locals() else None,
            "water_usage_liters": water_output if 'water_output' in locals() else None,
            "power_usage_kwh": power_output if 'power_output' in locals() else None,
            "yield_prediction": yield_output if 'yield_output' in locals() else None
        },
        "relay_states": relay_state,
        "serial_connected": open_serial()
    })


def keyboard_monitor():
    """Monitor keyboard input for 'q' key to print QR code and URL."""
    print("💡 Press 'q' to display QR code and URL")
    while True:
        try:
            if keyboard.is_pressed('q'):
                print("\n" + "="*60)
                print("📱 Smart Farm Access Information")
                print("="*60)
                print_network_url(config["ui"]["port"])
                print("="*60)
                time.sleep(2)  # Prevent multiple triggers
        except:
            pass
        time.sleep(0.1)


# --- Network URL + QR for other devices (3-tier fallback) ---
QR_FILE = "smartfarm_qr.png"


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _save_qr_png(url):
    """Save QR as PNG for fallback 2."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        path = os.path.join(os.path.dirname(__file__), QR_FILE)
        img.save(path)
        return path
    except Exception:
        return None


def print_network_url(port=5000):
    ip = get_local_ip()
    url = f"http://{ip}:{port}"
    sep = "=" * max(50, len(url) + 4)
    print("\n" + sep)
    # Primary: ASCII/Unicode QR via qrcode-terminal (scannable in terminal)
    try:
        import qrcode_terminal
        print("  📱 Scan QR code to access Smart Farm:", file=sys.stderr)
        qrcode_terminal.draw(url)
        print("  🌐 Or open: " + url, file=sys.stderr)
    except ImportError:
        # Fallback 1: package not installed
        print("  🌐 Open: " + url, file=sys.stderr)
        print("  📱 Install 'qrcode-terminal' for QR display: pip install qrcode-terminal", file=sys.stderr)
    except Exception:
        # Fallback 2: save PNG and reference file
        qr_path = _save_qr_png(url)
        print("  🌐 Open: " + url, file=sys.stderr)
        if qr_path:
            print("  📱 QR code saved as " + QR_FILE, file=sys.stderr)
        else:
            print("  (install 'qrcode-terminal' or 'qrcode[pil]' for QR)", file=sys.stderr)
    print(sep + "\n", file=sys.stderr)


# --- Main ---
if __name__ == "__main__":
    init_db()
    # Start serial reader thread
    threading.Thread(target=serial_reader_thread, daemon=True).start()
    
    # Start keyboard monitor thread
    threading.Thread(target=keyboard_monitor, daemon=True).start()
    
    # Start Flask app with config
    host = config["ui"]["host"]
    port = config["ui"]["port"]
    print(f"\n🌐 Or open: http://{socket.gethostbyname(socket.gethostname())}:{port}")
    print("=" * 50)
    app.run(host=host, port=port, debug=False, use_reloader=False)
