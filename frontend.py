import logging
import subprocess
import webbrowser
import shutil
import psutil
import time
import requests
from threading import Timer
from datetime import datetime, timedelta

import dash
from dash import dcc, html
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate
import plotly.graph_objs as go
import pandas as pd

# Import the backend data manager
from backend import DataManager

# ────────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP (Initialize here for the whole application)
# ────────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='app.log', # Log file name
    filemode='a' # Append mode
)

# Add a console handler for immediate feedback
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger('').addHandler(console_handler)

# ────────────────────────────────────────────────────────────────────────────────
# DATA MANAGER INITIALIZATION
# ────────────────────────────────────────────────────────────────────────────────

# Instantiate the DataManager
data_manager = DataManager()

# Start the background data collection
data_manager.start()

# Track last successful update
last_successful_update = datetime.now()
update_failures = 0
MAX_UPDATE_FAILURES = 3

# ────────────────────────────────────────────────────────────────────────────────
# DASH APP INITIALISATION
# ────────────────────────────────────────────────────────────────────────────────
app = dash.Dash(__name__, assets_folder='assets')

# --- Browser Management --- (Improved from plot.py)
chromium_process = None
chromium_restart_count = 0
MAX_CHROMIUM_RESTARTS = 5
browser_startup_time = None
monitoring_active = False
CHROMIUM_STARTUP_DELAY = 15  # Give chromium more time to fully start
CHROMIUM_CHECK_INTERVAL = 60  # Check less frequently to avoid race conditions

def is_chromium_running():
    """Check if chromium is still running with our specific parameters."""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['name'] and 'chromium' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if '--kiosk' in cmdline and '8050' in cmdline:
                    return True
        return False
    except Exception as e:
        logging.warning(f"Error checking chromium status: {e}")
        return False

def is_dash_server_ready():
    """Check if Dash server is responding before launching browser."""
    try:
        response = requests.get("http://127.0.0.1:8050/", timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def kill_chromium_processes():
    """Kill any existing chromium processes running our app."""
    try:
        killed_any = False
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['name'] and 'chromium' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if '--kiosk' in cmdline and '8050' in cmdline:
                    logging.info(f"Terminating chromium process PID {proc.info['pid']}")
                    proc.terminate()
                    killed_any = True
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
        if killed_any:
            time.sleep(3)  # Give more time after killing processes
    except Exception as e:
        logging.warning(f"Error killing chromium processes: {e}")

def open_browser() -> None:
    """Find chromium-browser and open it in kiosk mode pointing at the Dash app."""
    global chromium_process, chromium_restart_count, browser_startup_time, monitoring_active
    
    if chromium_restart_count >= MAX_CHROMIUM_RESTARTS:
        logging.error(f"Maximum chromium restart attempts ({MAX_CHROMIUM_RESTARTS}) reached. Not restarting.")
        return
    
    # Prevent concurrent browser launches
    current_time = time.time()
    if browser_startup_time and (current_time - browser_startup_time) < 10:
        logging.info("Browser launch already in progress, skipping duplicate launch")
        return
    
    browser_startup_time = current_time
    url = "http://127.0.0.1:8050/"
    chromium_path = shutil.which('chromium-browser')

    # Only kill existing processes if we're restarting (not initial launch)
    if chromium_restart_count > 0:
        kill_chromium_processes()

    if chromium_path:
        logging.info(f"Found chromium-browser at: {chromium_path}")
        try:
            chromium_process = subprocess.Popen(
                [
                    chromium_path,
                    "--kiosk",
                    "--force-dark-mode",
                    "--disable-restore-session-state",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu-sandbox",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                    "--start-fullscreen",
                    "--window-position=0,0",
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            chromium_restart_count += 1
            logging.info(f"Launched chromium in kiosk mode (PID: {chromium_process.pid}, restart #{chromium_restart_count})")
            
            # Start monitoring with proper delay and only if not already active
            if not monitoring_active:
                Timer(CHROMIUM_STARTUP_DELAY, start_chromium_monitoring).start()
            
        except Exception as e:
            logging.error(f"Failed to launch {chromium_path}: {e}")
            logging.info("Falling back to default browser.")
            webbrowser.open(url)
    else:
        logging.warning("chromium-browser not found in PATH. Opening default browser instead.")
        webbrowser.open(url)

def start_chromium_monitoring():
    """Start the chromium monitoring cycle with safeguards."""
    global monitoring_active
    monitoring_active = True
    monitor_chromium()

def monitor_chromium():
    """Monitor chromium process and restart if needed."""
    global chromium_process, monitoring_active
    
    if not monitoring_active:
        return
    
    try:
        current_time = time.time()
        
        # Don't check too soon after browser startup
        if browser_startup_time and (current_time - browser_startup_time) < CHROMIUM_STARTUP_DELAY:
            Timer(CHROMIUM_CHECK_INTERVAL, monitor_chromium).start()
            return
        
        # Check if we've hit the restart limit
        if chromium_restart_count >= MAX_CHROMIUM_RESTARTS:
            logging.error("Maximum restart limit reached, stopping monitoring")
            monitoring_active = False
            return
        
        if not is_chromium_running():
            logging.warning("Chromium process died, attempting restart")
            open_browser()
        else:
            # Schedule next check with longer interval
            Timer(CHROMIUM_CHECK_INTERVAL, monitor_chromium).start()
            
    except Exception as e:
        logging.error(f"Error in chromium monitoring: {e}")
        # Continue monitoring even if there's an error
        Timer(CHROMIUM_CHECK_INTERVAL, monitor_chromium).start()

# --- Blank Figure ---
def create_blank_fig(message: str = "No data available or graph error.") -> go.Figure:
    """Creates a blank figure with an optional message."""
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="#000000",
        plot_bgcolor="#000000",
        xaxis_visible=False,
        yaxis_visible=False,
        margin=dict(l=0, r=0, t=0, b=0),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=20, color="#ffffff"),
            )
        ]
    )
    return fig

blank_fig = create_blank_fig() # Default blank figure

# ────────────────────────────────────────────────────────────────────────────────
# DASH LAYOUT (Moved from plot.py)
# ────────────────────────────────────────────────────────────────────────────────

# Fetch and validate measurement interval
DEFAULT_INTERVAL_SEC = 60 # Default to 60 seconds
measurement_interval_sec = DEFAULT_INTERVAL_SEC
try:
    interval_val = data_manager.get_measurement_interval_sec()
    if isinstance(interval_val, (int, float)) and interval_val > 0:
        measurement_interval_sec = interval_val
        logging.info(f"Using measurement interval from DataManager: {measurement_interval_sec}s")
    else:
        logging.warning(
            f"Invalid interval from DataManager ('{interval_val}'). "
            f"Falling back to default: {DEFAULT_INTERVAL_SEC}s"
        )
except Exception as e:
    logging.error(
        f"Error getting measurement interval from DataManager: {e}. "
        f"Falling back to default: {DEFAULT_INTERVAL_SEC}s"
    )

app.layout = html.Div(
    [
        dcc.Graph(
            id="live-graph",
            figure=blank_fig, # Use the potentially messaged blank_fig
            style={"height": "100vh", "width": "100vw"},
            config={"displayModeBar": False},
        ),
        dcc.Interval(
            id="interval",
            interval=(measurement_interval_sec + 5) * 1000, # Use validated interval
            n_intervals=0
        ),
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
# CALLBACKS (Moved from plot.py, adapted to use DataManager)
# ────────────────────────────────────────────────────────────────────────────────
@app.callback(Output("live-graph", "figure"), [Input("interval", "n_intervals")])
def update_graph_live(_):
    """Update the graph with current data from DataManager."""
    global last_successful_update, update_failures
    
    try:
        current_time = datetime.now()
        time_since_last_update = (current_time - last_successful_update).total_seconds()
        
        # Check if we're getting updates frequently enough
        if time_since_last_update > measurement_interval_sec * 2:
            logging.warning(f"Long delay since last update: {time_since_last_update:.1f} seconds")
            update_failures += 1
            if update_failures >= MAX_UPDATE_FAILURES:
                logging.error("Multiple consecutive update failures. Attempting data manager restart...")
                data_manager.stop()
                data_manager.start()
                update_failures = 0
        
        current_data = data_manager.get_data()

        if current_data is None or current_data.empty:
            logging.warning("Update graph: Data is None or empty, returning informative blank figure.")
            return create_blank_fig("No data currently available from sensors.")

        # Check for stale data
        try:
            latest_timestamp = pd.to_datetime(current_data['Timestamp'].max())
            if latest_timestamp and not pd.isna(latest_timestamp):
                data_age = (current_time - latest_timestamp.to_pydatetime()).total_seconds()
                if data_age > measurement_interval_sec * 2:
                    logging.warning(f"Data is stale. Latest point is {data_age:.1f} seconds old")
                    return create_blank_fig(f"Data collection may be stuck. Last update: {latest_timestamp}")
        except Exception as e:
            logging.warning(f"Error checking data age: {e}")
            # Continue with plotting anyway

        fig = go.Figure()

        # Define traces, separating Wroclaw for secondary axis
        sensor_traces = [
            ("Sens1", "Poddasze", "#1f77b4"),  # Plotly Blue
            ("Sens2", "Kuchnia", "#ff7f0e"),    # Plotly Orange
            ("Sens3", "Pokój Maksia", "#d62728"), # Plotly Red
        ]
        weather_trace = ("Wroclaw", "Wrocław", "#2ca02c") # Plotly Green

        # Add sensor traces to the primary y-axis
        for col, name, color in sensor_traces:
            if col in current_data.columns and not current_data[col].isnull().all():
                trace_data = current_data[['Timestamp', col]].dropna()
                if not trace_data.empty:
                    fig.add_trace(go.Scatter(
                        x=trace_data['Timestamp'],
                        y=trace_data[col],
                        mode='lines+markers',
                        name=name,
                        yaxis='y1',
                        line=dict(color=color),
                        marker=dict(color=color)
                    ))

        # Add weather trace to the secondary y-axis
        col, name, color = weather_trace
        if col in current_data.columns and not current_data[col].isnull().all():
            trace_data = current_data[['Timestamp', col]].dropna()
            if not trace_data.empty:
                fig.add_trace(go.Scatter(
                    x=trace_data['Timestamp'],
                    y=trace_data[col],
                    mode='lines',
                    name=name,
                    yaxis='y2',
                    line=dict(color=color)
                ))

        if not fig.data:
            logging.warning("No traces added to the figure, returning informative blank figure.")
            return create_blank_fig("Data available but could not be plotted. Check sensor configurations.")

        # Update layout
        fig.update_layout(
            title=dict(
                text=f"Live Temperature Readings (Last Update: {current_time.strftime('%H:%M:%S')})",
                x=0.5,
                xanchor="center"
            ),
            xaxis_title="Timestamp",
            yaxis=dict(
                title=dict(
                    text="°C (Sensors)",
                    font=dict(color="#1f77b4")
                ),
                tickfont=dict(color="#1f77b4")
            ),
            yaxis2=dict(
                title=dict(
                    text="°C (Wrocław)",
                    font=dict(color=color)
                ),
                overlaying="y",
                side="right",
                showgrid=False,
                tickfont=dict(color=color)
            ),
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
            margin=dict(l=40, r=40, t=40, b=80, pad=0),
        )

        # Update success tracking
        last_successful_update = current_time
        update_failures = 0
        
        return fig
    except Exception as e:
        logging.error(f"Error updating graph: {e}", exc_info=True)
        update_failures += 1
        return create_blank_fig(f"Error generating graph: {type(e).__name__}")


# ────────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION BLOCK (Moved from plot.py)
# ────────────────────────────────────────────────────────────────────────────────

def wait_for_server_and_launch_browser():
    """Wait for Dash server to be ready, then launch browser."""
    max_wait = 30  # Maximum wait time in seconds
    wait_time = 0
    
    while wait_time < max_wait:
        if is_dash_server_ready():
            logging.info("Dash server is ready, launching browser")
            open_browser()
            return
        else:
            logging.info(f"Waiting for Dash server to be ready... ({wait_time}s)")
            time.sleep(2)
            wait_time += 2
    
    logging.warning("Dash server not ready after 30 seconds, launching browser anyway")
    open_browser()

if __name__ == "__main__":
    logging.info("Application starting.")
    # Start browser launch in background after server starts
    Timer(3, wait_for_server_and_launch_browser).start()
    
    try:
        app.run(
            debug=False,
            dev_tools_ui=False,
            dev_tools_props_check=False,
            host="0.0.0.0",
            port=8050,
        )
    except Exception as e:
        logging.error(f"Error starting Dash app: {e}")
        # Cleanup - stop monitoring
        try:
            monitoring_active = False
        except NameError:
            pass  # monitoring_active might not be defined yet
    # Note: The background thread in data_manager will exit automatically
    # when the main application exits because it's a daemon thread.
    # If you needed cleanup, you could call data_manager.stop() here,
    # but it's generally not required for daemon threads. 