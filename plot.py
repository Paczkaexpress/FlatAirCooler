import time
import os
import struct
import subprocess
from threading import Thread, Timer
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate
import plotly.graph_objs as go
import pandas as pd
from bluepy.btle import Peripheral, UUID, ADDR_TYPE_RANDOM

# ────────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────────

# Setup basic logging (now to file)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='app.log', # Log file name
    filemode='a' # Append mode
)

# Load environment variables from .env file
load_dotenv()
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
if not OPENWEATHERMAP_API_KEY:
    logging.error("OpenWeatherMap API key not found in environment variables or .env file.")
    # Optionally, exit or raise an error if the key is critical
    # exit(1)

WEATHER_LOCATION = "Wroclaw, PL"

DEVICES_MACS = [
    "A4:C1:38:57:34:4F",
    "A4:C1:38:E8:B3:77",
    "A4:C1:38:6A:80:BD",
]
SERVICE_UUID = UUID("ebe0ccb0-7a0a-4b0c-8a1a-6ff2997da3a6")
CHARACTERISTIC_UUID = UUID("ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6")

CSV_FILE = "historicalData.csv"
MAX_DATA_LEN = 500
MEASUREMENT_INTERVAL_MIN = 20
MEASUREMENT_INTERVAL_SEC = MEASUREMENT_INTERVAL_MIN * 60

# ────────────────────────────────────────────────────────────────────────────────
# DASH APP INITIALISATION
# ────────────────────────────────────────────────────────────────────────────────
app = dash.Dash(__name__, assets_folder='assets')

# DataFrame used only for plotting (contents are also written to CSV)
# Initialize empty first
data = pd.DataFrame(columns=["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"])

# --- Load Historical Data ---
logging.info(f"Attempting to load historical data from {CSV_FILE}")
try:
    if os.path.exists(CSV_FILE):
        historical_data = pd.read_csv(CSV_FILE, parse_dates=['Timestamp'])
        if not historical_data.empty and 'Timestamp' in historical_data.columns:
            three_days_ago = datetime.now() - timedelta(days=3)
            # Ensure Timestamp column is timezone-naive for comparison if needed,
            # assuming pd.Timestamp.now() used later is also naive.
            historical_data['Timestamp'] = pd.to_datetime(historical_data['Timestamp']).dt.tz_localize(None)
            three_days_ago = three_days_ago.tz_localize(None) # Make comparison compatible

            recent_data = historical_data[historical_data['Timestamp'] >= three_days_ago].copy()

            # Ensure required columns exist after loading
            required_cols = ["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"]
            for col in required_cols:
                if col not in recent_data.columns:
                    logging.warning(f"Column '{col}' not found in historical data, adding with NaN.")
                    recent_data[col] = pd.NA # Use pandas' NA marker

            # Reorder columns to match the expected format
            recent_data = recent_data[required_cols]

            if len(recent_data) > MAX_DATA_LEN:
                logging.info(f"Loaded {len(recent_data)} rows from the last 3 days. Truncating to {MAX_DATA_LEN} most recent.")
                data = recent_data.iloc[-MAX_DATA_LEN:]
            else:
                logging.info(f"Loaded {len(recent_data)} rows from the last 3 days.")
                data = recent_data
        else:
            logging.info(f"{CSV_FILE} is empty or doesn't contain a valid 'Timestamp' column.")
            # data remains the empty DataFrame initialized earlier
    else:
        logging.info(f"{CSV_FILE} not found. Starting with empty data.")
        # data remains the empty DataFrame initialized earlier
except Exception as e:
    logging.error(f"Error loading or processing historical data from {CSV_FILE}: {e}")
    # data remains the empty DataFrame initialized earlier
# --- Load Historical Data ---

# ────────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ────────────────────────────────────────────────────────────────────────────────

def get_wroclaw_temperature(api_key: str):
    """Fetch current temperature for Wrocław from OpenWeatherMap."""
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": WEATHER_LOCATION,
        "appid": api_key,
        "units": "metric"
    }
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        weather_data = response.json()
        temp = weather_data.get("main", {}).get("temp")
        if temp is not None:
            logging.info(f"Successfully fetched Wrocław temperature: {temp}°C")
            return float(temp)
        else:
            logging.warning("Could not find temperature in OpenWeatherMap response.")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching OpenWeatherMap data: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred fetching weather: {e}")
        return None

def open_browser() -> None:
    """Open Chromium in kiosk mode pointing at the Dash app."""
    url = "http://127.0.0.1:8050/"
    chromium_path = "/usr/bin/chromium-browser"
    subprocess.Popen(
        [
            chromium_path,
            "--kiosk",
            "--force-dark-mode",
            "--disable-restore-session-state",
            "--disable-infobars",
            url,
        ]
    )


def get_temperature_humidity(mac_address: str):
    """Read temperature, humidity, battery level from a Xiaomi BLE sensor."""
    max_retries = 3
    retry_delay_sec = 2

    for attempt in range(max_retries):
        try:
            logging.info(f"Attempt {attempt + 1}/{max_retries} connecting to {mac_address}")
            # Connect WITHOUT explicit address type
            device = Peripheral(mac_address)
            logging.info(f"Connected to {mac_address}. Reading data...")

            logging.info(f"Getting service {SERVICE_UUID}...")
            service = device.getServiceByUUID(SERVICE_UUID)
            logging.info(f"Got service. Getting characteristic {CHARACTERISTIC_UUID}...")
            characteristic = service.getCharacteristics(CHARACTERISTIC_UUID)[0]
            logging.info("Got characteristic. Reading data...")
            raw = characteristic.read()
            logging.info("Read successful. Unpacking data...")
            temp_raw, hum, batt = struct.unpack("<HbH", raw)

            logging.info("Disconnecting...")
            device.disconnect()
            logging.info(f"Successfully read data and disconnected from {mac_address}.")
            return temp_raw / 100.0, hum, batt / 1000.0
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1} failed for {mac_address}: {e}")
            # Ensure disconnected if connection partially succeeded
            try:
                device.disconnect()
            except Exception:
                pass # Ignore disconnection errors during retry
            if attempt < max_retries - 1:
                logging.info(f"Retrying in {retry_delay_sec} seconds...")
                time.sleep(retry_delay_sec)
            else:
                logging.error(f"Failed to connect to {mac_address} after {max_retries} attempts.")
                raise # Re-raise the exception to be caught by generate_data_point

    # This part should ideally not be reached if retries fail, due to the raise
    # But as a fallback, raise an error
    raise ConnectionError(f"Could not connect to {mac_address} after retries")


prev_temp = [22.0] * len(DEVICES_MACS)

def generate_data_point():
    """Poll sensors and weather, append the row to disk & in-memory DF."""
    global data, prev_temp
    logging.info("Starting data point generation.")

    timestamp = pd.Timestamp.now()
    temps = []

    # --- Get Sensor Data ---
    for i, mac in enumerate(DEVICES_MACS):
        try:
            t, _, _ = get_temperature_humidity(mac)
            logging.info(f"Successfully read sensor {mac}: {t}°C")
        except Exception as e:
            # Log the actual error from get_temperature_humidity if it re-raised
            logging.warning(f"Failed to read sensor {mac}, using previous value {prev_temp[i]}°C. Error: {e}")
            t = prev_temp[i]
        temps.append(t)

    prev_temp = temps.copy()

    # --- Get Weather Data ---
    wroclaw_temp = None # Initialize
    if OPENWEATHERMAP_API_KEY: # Check if key exists
        wroclaw_temp = get_wroclaw_temperature(OPENWEATHERMAP_API_KEY)
    else:
        logging.warning("Skipping OpenWeatherMap fetch: API key not configured.")
    # If API fails, we might want a fallback (e.g., None, NaN, or previous value)
    # For now, it returns None on failure.

    # --- Create and Save Row ---
    new_row = pd.DataFrame(
        {
            "Timestamp": [timestamp],
            "Sens1": [temps[0]],
            "Sens2": [temps[1]],
            "Sens3": [temps[2]],
            "Wroclaw": [wroclaw_temp], # Added Wroclaw temp
        }
    )

    new_row.to_csv(CSV_FILE, mode="a", index=False, header=not os.path.exists(CSV_FILE))

    data = pd.concat([data, new_row], ignore_index=True)
    if len(data) > MAX_DATA_LEN:
        data = data.iloc[-MAX_DATA_LEN:]

    logging.info(f"Finished data point generation. New row: {new_row.to_dict('records')[0]}")


# ────────────────────────────────────────────────────────────────────────────────
# BACKGROUND SAMPLING THREAD
# ────────────────────────────────────────────────────────────────────────────────

def background_thread():
    """Generate the first datapoint immediately, then repeat every interval."""
    logging.info("Background thread started.")
    try:
        generate_data_point()  # immediate first read
    except Exception as e:
        logging.error(f"Error during initial data point generation in background thread: {e}")

    while True:
        try:
            generate_data_point()
        except Exception as e:
            # Log the error and continue the loop
            logging.error(f"Error during data point generation in background thread: {e}")
            # Optional: Add a short delay before retrying the next cycle?
            # time.sleep(60) # e.g., wait 60 seconds before next attempt
        time.sleep(MEASUREMENT_INTERVAL_SEC)

thread = Thread(target=background_thread, daemon=True)
thread.start()

# ────────────────────────────────────────────────────────────────────────────────
# DASH LAYOUT
# ────────────────────────────────────────────────────────────────────────────────
blank_fig = go.Figure()
blank_fig.update_layout(
    paper_bgcolor="#000000",
    plot_bgcolor="#000000",
    xaxis_visible=False,
    yaxis_visible=False,
    margin=dict(l=0, r=0, t=0, b=0),
)

app.layout = html.Div(
    [
        dcc.Graph(
            id="live-graph",
            figure=blank_fig,
            style={"height": "100vh", "width": "100vw"},
            config={"displayModeBar": False},
        ),
        dcc.Interval(id="interval", interval=(MEASUREMENT_INTERVAL_SEC + 5) * 1000, n_intervals=0),
    ],
    style={
        "backgroundColor": "#121212",
        "color": "#ffffff",
        "height": "100vh",
        "width": "100vw",
        "margin": 0,
        "padding": 0,
        "overflow": "hidden",
    },
)

# ────────────────────────────────────────────────────────────────────────────────
# CALLBACKS
# ────────────────────────────────────────────────────────────────────────────────
@app.callback(Output("live-graph", "figure"), [Input("interval", "n_intervals")])
def update_graph_live(_):
    if data.empty:
        return blank_fig

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data["Timestamp"], y=data["Sens1"], mode="lines+markers", name="Poddasze"))
    fig.add_trace(go.Scatter(x=data["Timestamp"], y=data["Sens2"], mode="lines+markers", name="Kuchnia"))
    fig.add_trace(go.Scatter(x=data["Timestamp"], y=data["Sens3"], mode="lines+markers", name="Pokój Maksia"))
    fig.add_trace(go.Scatter(x=data["Timestamp"], y=data["Wroclaw"], mode="lines+markers", name="Wrocław"))

    fig.update_layout(
        title="Live Temperature Readings",
        xaxis_title="Timestamp",
        yaxis_title="°C",
        template="plotly_dark",
        uirevision=True,
        paper_bgcolor="#000000",
        plot_bgcolor="#000000",
        legend=dict(
            orientation="h",
            y=-0.25,
            x=0.5,
            xanchor="center",
        ),
        legend_font_size=18,
        margin=dict(l=0, r=0, t=0, b=0, pad=0),
    )
    return fig


# ────────────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.info("Application starting.")
    Timer(1, open_browser).start()
    app.run_server(
        debug=False,
        dev_tools_ui=False,
        dev_tools_props_check=False,
        host="0.0.0.0",
        port=8050,
    )