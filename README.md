# BLE Temperature Sensor Dashboard

This Python script reads temperature data from multiple Xiaomi BLE temperature/humidity sensors and current weather data from OpenWeatherMap for a specified location. It displays the collected data in a live-updating web dashboard using Dash and Plotly, and logs all readings to a CSV file.

## Features

*   Connects to multiple specified BLE sensors.
*   Fetches current external temperature from OpenWeatherMap.
*   Logs sensor readings and external temperature to `historicalData.csv`.
*   Displays a live-updating line chart of temperatures via a Dash web interface.
*   Automatically opens the dashboard in Chromium kiosk mode on startup (Linux).
*   Includes error handling for BLE connections and web requests.
*   Logs application events and errors to `app.log`.

## Prerequisites

*   Python 3.x
*   `pip` (Python package installer)
*   Bluetooth adapter on the machine running the script.
*   Linux operating system (due to `bluepy` and Chromium path) - `bluepy` might require specific setup:
    *   `sudo apt-get install python3-pip libglib2.0-dev libbluetooth-dev`
    *   The user running the script might need permissions to access Bluetooth without `sudo` (e.g., being in the `bluetooth` group).
*   `chromium-browser` installed at `/usr/bin/chromium-browser` (if using the auto-open feature).

## Configuration

Before running, configure the following constants within `plot.py`:

*   `OPENWEATHERMAP_API_KEY`: Your API key from [OpenWeatherMap](https://openweathermap.org/).
*   `WEATHER_LOCATION`: The location for weather data (e.g., "Wroclaw, PL").
*   `DEVICES_MACS`: A list of the MAC addresses of your Xiaomi BLE sensors.
*   `MEASUREMENT_INTERVAL_MIN`: How often (in minutes) to poll the sensors and update the plot.

## Setup

1.  **Clone the repository or download the files.**
2.  **Navigate to the script directory:**
    ```bash
    cd path/to/Software
    ```
3.  **Create and activate a virtual environment (recommended):**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```
4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **Ensure Bluetooth is enabled and necessary permissions are set for `bluepy`.** You might need to run the script with `sudo` the first time or adjust user permissions.

## Running the Application

```bash
python plot.py
```

The script will:

1.  Start logging to `app.log`.
2.  Start the background thread to poll sensors and weather.
3.  Start the Dash web server (usually on `http://0.0.0.0:8050/`).
4.  Attempt to open Chromium in kiosk mode pointing to the dashboard.

Data will be appended to `historicalData.csv` at each measurement interval.

## Stopping the Application

Press `CTRL+C` in the terminal where the script is running. 