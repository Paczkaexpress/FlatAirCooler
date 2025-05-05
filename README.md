# Flat Air Cooler - Temperature Monitor

This application monitors temperature using Xiaomi BLE sensors and plots the data alongside the current temperature in Wrocław using Dash.

## Architecture

The application is split into two main modules:

*   `backend.py`: Handles all data acquisition (BLE sensor reading via `bluepy`, OpenWeatherMap API fetching), data processing (using `pandas`), saving data to `historicalData.csv`, and manages the background polling thread.
*   `frontend.py`: Sets up and runs the Dash web application, defines the layout (using `dash_html_components`, `dash_core_components`), creates the plots (using `plotly`), and manages callbacks to update the graph with data fetched from the `DataManager` in `backend.py`. It also handles opening the browser in kiosk mode.

## Files

*   `frontend.py`: Main application script to run the Dash server and UI.
*   `backend.py`: Data handling and background processing logic.
*   `historicalData.csv`: Stores historical temperature readings.
*   `app.log`: Log file for application events and errors.
*   `.env`: (Optional/Required) Stores the `OPENWEATHERMAP_API_KEY`.
*   `requirements.txt`: Lists Python dependencies.
*   `assets/`: Folder for Dash assets (like custom CSS, if any).

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd <repo-folder>
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Install `bluepy` system dependencies** (if not already installed):
    ```bash
    sudo apt-get update
    sudo apt-get install python3-pip libglib2.0-dev libbluetooth-dev
    # Install bluepy via pip (should be in requirements.txt too)
    pip install bluepy
    ```
4.  **(Optional/Required) Create `.env` file:**
    Create a file named `.env` in the root directory and add your OpenWeatherMap API key:
    ```
    OPENWEATHERMAP_API_KEY=your_actual_api_key_here
    ```
    *Note: If you don't provide an API key, the Wrocław temperature will not be fetched or plotted.*

5.  **Bluetooth Permissions:** Ensure your user has the necessary permissions to interact with Bluetooth devices. You might need to run the script with `sudo` or configure Bluetooth permissions appropriately.

## Running the Application

Execute the frontend script:

```bash
python frontend.py
```

Or, if Bluetooth requires root privileges:

```bash
sudo python frontend.py
```

The script will:
1.  Load historical data from `historicalData.csv`.
2.  Start a background thread to poll sensors and weather data every minute.
3.  Start the Dash web server on `http://0.0.0.0:8050/`.
4.  Attempt to open `chromium-browser` in kiosk mode pointing to the app (falling back to the default browser if `chromium-browser` isn't found).

Data will be appended to `historicalData.csv` at each measurement interval.

## Stopping the Application

Press `CTRL+C` in the terminal where the script is running. 