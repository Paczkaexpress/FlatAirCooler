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
from bluepy.btle import Peripheral, UUID, ADDR_TYPE_RANDOM, BTLEException
from collections import deque

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
MEASUREMENT_INTERVAL_MIN = 20
MEASUREMENT_INTERVAL_SEC = MEASUREMENT_INTERVAL_MIN * 60
MIN_SLEEP_SEC = 5  # Minimum sleep time to prevent busy-loop


class DataManager:
    def __init__(self):
        # Use deque instead of pandas for memory efficiency
        self.recent_data = deque(maxlen=MAX_DATA_LEN)
        self.data = pd.DataFrame(columns=["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"])
        self.prev_temp = [22.0] * len(DEVICES_MACS)
        self._load_historical_data()
        self.thread = None
        self.running = False
        self.last_successful_read = datetime.now()
        self.consecutive_failures = 0
        self.max_consecutive_failures = 5
        
        # BLE connection management
        self.ble_connections = {}  # Store persistent connections
        self.connection_retry_count = {}  # Track retry attempts per device
        
        # Timer management to fix thread leak
        self.watchdog_timer = None

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
                    recent_data = recent_data.tail(MAX_DATA_LEN)

                # Populate deque with recent data for memory efficiency
                for _, row in recent_data.iterrows():
                    data_point = {
                        "Timestamp": row['Timestamp'],
                        "Sens1": row['Sens1'] if pd.notna(row['Sens1']) else None,
                        "Sens2": row['Sens2'] if pd.notna(row['Sens2']) else None,
                        "Sens3": row['Sens3'] if pd.notna(row['Sens3']) else None,
                        "Wroclaw": row['Wroclaw'] if pd.notna(row['Wroclaw']) else None,
                    }
                    self.recent_data.append(data_point)

                # Keep DataFrame for compatibility with any remaining code
                self.data = recent_data

                logging.info(f"Successfully loaded {len(self.recent_data)} rows of historical data")

                if recent_data['Timestamp'].isna().any():
                    logging.warning("Found NaN timestamps in loaded data")
                for col in numeric_columns:
                    nan_count = recent_data[col].isna().sum()
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

    def _connect_to_device(self, mac_address: str):
        """Establish and maintain a persistent connection to a BLE device."""
        try:
            if mac_address in self.ble_connections:
                # Test existing connection
                try:
                    # Quick test - if this fails, connection is dead
                    self.ble_connections[mac_address].getServices()
                    return self.ble_connections[mac_address]
                except:
                    # Connection is dead, clean it up
                    try:
                        self.ble_connections[mac_address].disconnect()
                    except:
                        pass
                    del self.ble_connections[mac_address]
            
            # Create new connection
            logging.info(f"Establishing persistent connection to {mac_address}")
            device = Peripheral(mac_address)
            self.ble_connections[mac_address] = device
            self.connection_retry_count[mac_address] = 0
            logging.info(f"Successfully connected to {mac_address}")
            return device
            
        except Exception as e:
            self.connection_retry_count[mac_address] = self.connection_retry_count.get(mac_address, 0) + 1
            logging.error(f"Failed to connect to {mac_address}: {e}")
            if mac_address in self.ble_connections:
                del self.ble_connections[mac_address]
            return None

    def _disconnect_all_devices(self):
        """Clean up all BLE connections."""
        for mac_address, device in self.ble_connections.items():
            try:
                device.disconnect()
                logging.info(f"Disconnected from {mac_address}")
            except Exception as e:
                logging.warning(f"Error disconnecting from {mac_address}: {e}")
        self.ble_connections.clear()
        self.connection_retry_count.clear()

    def _get_temperature_humidity(self, mac_address: str):
        """Read temperature, humidity, battery level from a Xiaomi BLE sensor using persistent connection."""
        max_retries = 3
        
        for attempt in range(max_retries):
            device = self._connect_to_device(mac_address)
            if device is None:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise ConnectionError(f"Could not connect to {mac_address} after {max_retries} attempts")
            
            try:
                logging.info(f"Reading from {mac_address} (attempt {attempt + 1}/{max_retries})")
                service = device.getServiceByUUID(SERVICE_UUID)
                characteristic = service.getCharacteristics(CHARACTERISTIC_UUID)[0]
                raw = characteristic.read()
                temp_raw, hum, batt = struct.unpack("<HbH", raw)
                
                logging.info(f"Successfully read data from {mac_address}")
                return temp_raw / 100.0, hum, batt / 1000.0
                
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1} failed for {mac_address}: {e}")
                # Remove failed connection
                if mac_address in self.ble_connections:
                    try:
                        self.ble_connections[mac_address].disconnect()
                    except:
                        pass
                    del self.ble_connections[mac_address]
                
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    raise ConnectionError(f"Failed to read from {mac_address} after {max_retries} attempts")

    def _generate_data_point(self):
        """Poll sensors and weather, append the row to disk & in-memory DF.
        
        Returns:
            bool: True if all measurements succeeded, False otherwise
        """
        start_time = datetime.now()
        logging.info("Starting data point generation at %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))

        try:
            timestamp = pd.Timestamp.now()
            temps = []  # Initialize empty temperature list
            all_success = True

            # Read each sensor with retries
            for i, mac in enumerate(DEVICES_MACS):
                retries = 3
                sensor_success = False
                
                # Only retry if the sensor read fails
                while retries > 0 and not sensor_success:
                    try:
                        t, h, b = self._get_temperature_humidity(mac)
                        logging.info(f"Successfully read sensor {mac}: {t}°C, humidity: {h}%, battery: {b}V")
                        temps.append(t)
                        self.prev_temp[i] = t  # Update previous temp on success
                        sensor_success = True
                    except Exception as e:
                        retries -= 1
                        if retries > 0:
                            logging.warning(f"Failed to read sensor {mac}, attempts remaining: {retries}. Error: {e}")
                            time.sleep(2)  # Wait before retry
                        else:
                            logging.error(f"Failed to read sensor {mac} after all retries. Error: {e}")
                            temps.append(pd.NA)
                            all_success = False

            # Get weather data with retries
            weather_retries = 3
            wroclaw_temp = None
            
            while weather_retries > 0 and wroclaw_temp is None:
                wroclaw_temp = self._get_wroclaw_temperature()
                if wroclaw_temp is None:
                    weather_retries -= 1
                    if weather_retries > 0:
                        logging.warning(f"Failed to get weather data, attempts remaining: {weather_retries}")
                        time.sleep(2)  # Wait before retry
                    else:
                        logging.error("Failed to get weather data after all retries")
                        all_success = False

                            # Proceed with data storage (even with partial failures to maintain consistency)
            data_point = {
                "Timestamp": timestamp,
                "Sens1": temps[0] if len(temps) > 0 else None,
                "Sens2": temps[1] if len(temps) > 1 else None,
                "Sens3": temps[2] if len(temps) > 2 else None,
                "Wroclaw": wroclaw_temp,
            }

            # Write to CSV - create DataFrame only for CSV writing
            try:
                new_row = pd.DataFrame([data_point])
                new_row.to_csv(CSV_FILE, mode="a", index=False, header=not os.path.exists(CSV_FILE))
                logging.info(f"Successfully appended data to {CSV_FILE}")
                
                # Store in memory-efficient deque
                self.recent_data.append(data_point)
                
                if all_success:
                    self.consecutive_failures = 0
                    self.last_successful_read = datetime.now()
                else:
                    self.consecutive_failures += 1
                    if self.consecutive_failures >= self.max_consecutive_failures:
                        logging.error(f"Hit {self.consecutive_failures} consecutive failures. Triggering thread restart...")
                        self.stop()
                        self.start()
                
            except Exception as e:
                logging.error(f"Failed to write to CSV file '{CSV_FILE}': {e}")
                all_success = False
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.max_consecutive_failures:
                    logging.error(f"Hit {self.consecutive_failures} consecutive failures. Triggering thread restart...")
                    self.stop()
                    self.start()

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logging.info(f"Finished data point generation in {duration:.1f} seconds. Success: {all_success}")
            
            return all_success

        except Exception as e:
            logging.error(f"Critical error in _generate_data_point: {e}", exc_info=True)
            self.consecutive_failures += 1
            return False


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

                # Calculate sleep time with minimum sleep to prevent busy-loop
                elapsed_time = time.monotonic() - start_time
                sleep_duration = max(MIN_SLEEP_SEC, MEASUREMENT_INTERVAL_SEC - elapsed_time)
                logging.debug(f"Data point generated successfully. Sleeping for {sleep_duration:.2f} seconds.")
                time.sleep(sleep_duration)

            except Exception as e:
                # Log the error and wait for the normal interval before the next attempt
                logging.error(f"Error during data point generation in background thread: {e}")

                # Wait standard interval even after failure before retrying
                elapsed_time = time.monotonic() - start_time
                sleep_duration = max(MIN_SLEEP_SEC, MEASUREMENT_INTERVAL_SEC - elapsed_time)
                logging.warning(f"Data generation failed. Waiting {sleep_duration:.2f} seconds before next attempt.")
                time.sleep(sleep_duration)

    def _check_thread_health(self):
        """Check if the background thread is healthy and restart if necessary."""
        if self.thread is None or not self.thread.is_alive():
            logging.error("Background thread died. Attempting restart...")
            self.stop()
            self.start()
            return

        # Check if we haven't had a successful read in too long
        time_since_last_read = (datetime.now() - self.last_successful_read).total_seconds()
        if time_since_last_read > MEASUREMENT_INTERVAL_SEC * 2:
            logging.error(f"No successful reads in {time_since_last_read:.1f} seconds. Attempting thread restart...")
            self.stop()
            self.start()

    def start(self):
        """Start the background data collection thread."""
        if not self.running:
            self.running = True
            self.consecutive_failures = 0
            self.last_successful_read = datetime.now()
            self.thread = Thread(target=self._background_loop, daemon=True)
            self.thread.start()
            logging.info("Background data collection thread started.")
            
            # Start watchdog timer
            self._start_watchdog()

    def _start_watchdog(self):
        """Start a watchdog timer to monitor thread health."""
        # Cancel any existing timer first to prevent leak
        if self.watchdog_timer is not None:
            self.watchdog_timer.cancel()
            
        if self.running:
            self.watchdog_timer = Timer(MEASUREMENT_INTERVAL_SEC, self._watchdog_check)
            self.watchdog_timer.start()

    def _watchdog_check(self):
        """Watchdog timer callback to check thread health."""
        if self.running:
            self._check_thread_health()
            self._start_watchdog()  # Schedule next check

    def stop(self):
        """Stop the background data collection thread."""
        if self.running:
            self.running = False
            
            # Cancel the watchdog timer to prevent thread leak
            if self.watchdog_timer is not None:
                self.watchdog_timer.cancel()
                self.watchdog_timer = None
                
            if self.thread:
                logging.info("Stopping background data collection thread...")
                # No join needed for daemon threads
                self.thread = None
                
            # Clean up BLE connections
            self._disconnect_all_devices()
            logging.info("Background data collection thread stopped.")

    def get_data(self):
        """Return the current data DataFrame."""
        # Convert deque to DataFrame for compatibility with existing frontend
        if self.recent_data:
            df = pd.DataFrame(list(self.recent_data))
            # Ensure columns are in the expected order
            column_order = ["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"]
            for col in column_order:
                if col not in df.columns:
                    df[col] = None
            return df[column_order].copy()
        else:
            # Return empty DataFrame with expected structure
            return pd.DataFrame(columns=["Timestamp", "Sens1", "Sens2", "Sens3", "Wroclaw"])

    def get_measurement_interval_sec(self):
        """Returns the measurement interval in seconds."""
        return MEASUREMENT_INTERVAL_SEC 