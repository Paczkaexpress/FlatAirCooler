import time
import os
import struct
import subprocess
from threading import Thread, Timer
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
from bluepy.btle import Peripheral, UUID, ADDR_TYPE_RANDOM

# Load environment variables from .env file
load_dotenv()

# ────────────────────────────────────────────────────────────────────────────────
# CONFIGURATION (Moved here from plot.py)
# ────────────────────────────────────────────────────────────────────────────────
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
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
MEASUREMENT_INTERVAL_MIN = 1
MEASUREMENT_INTERVAL_SEC = MEASUREMENT_INTERVAL_MIN * 60


class DataManager:
    def __init__(self):
        self.data = pd.DataFrame(columns=["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"])
        self.prev_temp = [22.0] * len(DEVICES_MACS)
        self._load_historical_data()
        self.thread = None
        self.running = False

        if not OPENWEATHERMAP_API_KEY:
            logging.warning("OpenWeatherMap API key not found. Weather data will not be fetched.")


    def _load_historical_data(self):
        """Load and process historical data from CSV file."""
        logging.info(f"Attempting to load historical data from {CSV_FILE}")
        try:
            if os.path.exists(CSV_FILE):
                historical_data = pd.read_csv(CSV_FILE)
                if historical_data.empty:
                    logging.info(f"{CSV_FILE} is empty. Starting with empty data.")
                    return

                try:
                    historical_data['Timestamp'] = pd.to_datetime(historical_data['Timestamp'])
                except Exception as e:
                    logging.error(f"Error parsing timestamps: {e}")
                    return

                historical_data['Timestamp'] = historical_data['Timestamp'].dt.tz_localize(None)

                numeric_columns = ["Sens1", "Sens2", "Sens3", "Wroclaw"]
                for col in numeric_columns:
                    if col in historical_data.columns:
                        try:
                            historical_data[col] = pd.to_numeric(historical_data[col], errors='coerce')
                        except Exception as e:
                            logging.error(f"Error converting {col} to numeric: {e}")
                    else:
                        logging.warning(f"Column {col} not found in CSV, adding with NaN values")
                        historical_data[col] = pd.NA

                three_days_ago = pd.Timestamp.now() - pd.Timedelta(days=3)
                recent_data = historical_data[historical_data['Timestamp'] >= three_days_ago].copy()

                required_cols = ["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"]
                for col in required_cols:
                    if col not in recent_data.columns:
                        recent_data[col] = pd.NA

                recent_data = recent_data[required_cols]

                if len(recent_data) > MAX_DATA_LEN:
                    logging.info(f"Truncating to {MAX_DATA_LEN} most recent entries")
                    self.data = recent_data.tail(MAX_DATA_LEN)
                else:
                    self.data = recent_data

                logging.info(f"Successfully loaded {len(self.data)} rows of historical data")

                if self.data['Timestamp'].isna().any():
                    logging.warning("Found NaN timestamps in loaded data")
                for col in numeric_columns:
                    nan_count = self.data[col].isna().sum()
                    if nan_count > 0:
                        logging.warning(f"Found {nan_count} NaN values in {col}")

            else:
                logging.info(f"{CSV_FILE} not found. Starting with empty data.")

        except Exception as e:
            logging.error(f"Error loading historical data: {e}")
            self.data = pd.DataFrame(columns=["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"])

    def _get_wroclaw_temperature(self):
        """Fetch current temperature for Wrocław from OpenWeatherMap."""
        if not OPENWEATHERMAP_API_KEY:
             return None # Skip if no API key
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": WEATHER_LOCATION,
            "appid": OPENWEATHERMAP_API_KEY,
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

    def _get_temperature_humidity(self, mac_address: str):
        """Read temperature, humidity, battery level from a Xiaomi BLE sensor."""
        max_retries = 3
        retry_delay_sec = 2
        device = None

        for attempt in range(max_retries):
            try:
                logging.info(f"Attempt {attempt + 1}/{max_retries} connecting to {mac_address}")
                device = None
                device = Peripheral(mac_address)
                logging.info(f"Connected to {mac_address}. Reading data...")

                service = device.getServiceByUUID(SERVICE_UUID)
                characteristic = service.getCharacteristics(CHARACTERISTIC_UUID)[0]
                raw = characteristic.read()
                temp_raw, hum, batt = struct.unpack("<HbH", raw)

                logging.info("Disconnecting...")
                device.disconnect()
                device = None
                logging.info(f"Successfully read data and disconnected from {mac_address}.")
                return temp_raw / 100.0, hum, batt / 1000.0
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1} failed for {mac_address}: {e}")
                if device is not None:
                    try:
                        device.disconnect()
                    except Exception as disconnect_error:
                        logging.warning(f"Error during disconnect cleanup: {disconnect_error}")
                    device = None

                if attempt < max_retries - 1:
                    logging.info(f"Retrying in {retry_delay_sec} seconds...")
                    time.sleep(retry_delay_sec)
                else:
                    logging.error(f"Failed to connect to {mac_address} after {max_retries} attempts.")
                    raise # Re-raise the exception after final retry

        # This should technically not be reachable if max_retries > 0
        raise ConnectionError(f"Could not connect to {mac_address} after retries")


    def _generate_data_point(self):
        """Poll sensors and weather, append the row to disk & in-memory DF."""
        logging.info("Starting data point generation.")

        timestamp = pd.Timestamp.now()
        temps = [] # Stores temperatures for the *current* data point

        for i, mac in enumerate(DEVICES_MACS):
            try:
                t, _, _ = self._get_temperature_humidity(mac)
                logging.info(f"Successfully read sensor {mac}: {t}°C")
                temps.append(t)
                self.prev_temp[i] = t # Update previous temp only on success
            except Exception as e:
                logging.warning(f"Failed to read sensor {mac}, recording NaN for this point. Last known value was {self.prev_temp[i]}°C. Error: {e}")
                temps.append(pd.NA) # Append NA if read fails

        # self.prev_temp is updated individually on success, no need to copy whole list here

        wroclaw_temp = self._get_wroclaw_temperature()

        # Ensure temps list has the correct length, padding with NA if necessary
        while len(temps) < len(DEVICES_MACS):
            temps.append(pd.NA)

        new_row = pd.DataFrame(
            {
                "Timestamp": [timestamp],
                "Sens1": [temps[0]],
                "Sens2": [temps[1]],
                "Sens3": [temps[2]],
                "Wroclaw": [wroclaw_temp],
            }
        )

        # Ensure the directory exists before writing
        logging.info(f"Attempting to use CSV file path: '{CSV_FILE}'")
        try:
            new_row.to_csv(CSV_FILE, mode="a", index=False, header=not os.path.exists(CSV_FILE))
            logging.info(f"Successfully appended data to {CSV_FILE}")
        except Exception as e:
            logging.error(f"Failed to write to CSV file '{CSV_FILE}': {e}")
            # Optionally re-raise the exception if you want the main loop's error handling to catch it too
            # raise

        # Use concat instead of append (append is deprecated)
        self.data = pd.concat([self.data, new_row], ignore_index=True)
        if len(self.data) > MAX_DATA_LEN:
            self.data = self.data.iloc[-MAX_DATA_LEN:]

        logging.info(f"Finished data point generation. New row: {new_row.to_dict('records')[0]}")


    def _background_loop(self):
        """Generate the first datapoint immediately, then repeat every interval."""
        logging.info("Background thread started.")

        # --- Initial data point generation ---
        try:
            self._generate_data_point()
        except Exception as e:
            # Log the error, continue to main loop
            logging.error(f"Error during initial data point generation in background thread: {e}")

        # --- Main loop ---
        while self.running:
            start_time = time.monotonic()
            try:
                self._generate_data_point()

                # Calculate sleep time, ensuring it's non-negative
                elapsed_time = time.monotonic() - start_time
                sleep_duration = max(0, MEASUREMENT_INTERVAL_SEC - elapsed_time)
                logging.debug(f"Data point generated successfully. Sleeping for {sleep_duration:.2f} seconds.")
                time.sleep(sleep_duration)

            except Exception as e:
                # Log the error and wait for the normal interval before the next attempt
                logging.error(f"Error during data point generation in background thread: {e}")

                # Wait standard interval even after failure before retrying
                elapsed_time = time.monotonic() - start_time
                sleep_duration = max(0, MEASUREMENT_INTERVAL_SEC - elapsed_time)
                logging.warning(f"Data generation failed. Waiting {sleep_duration:.2f} seconds before next attempt.")
                time.sleep(sleep_duration)

    def start(self):
        """Start the background data collection thread."""
        if not self.running:
            self.running = True
            self.thread = Thread(target=self._background_loop, daemon=True)
            self.thread.start()
            logging.info("Background data collection thread started.")

    def stop(self):
        """Stop the background data collection thread."""
        if self.running:
            self.running = False
            if self.thread:
                # No join needed for daemon threads, they exit with the main program
                # self.thread.join() # Optionally join if not daemon
                pass
            logging.info("Background data collection thread stopped.")

    def get_data(self):
        """Return the current data DataFrame."""
        # Return a copy to prevent modification from outside
        return self.data.copy()

    def get_measurement_interval_sec(self):
        """Returns the measurement interval in seconds."""
        return MEASUREMENT_INTERVAL_SEC 