import logging
import subprocess
import webbrowser
import shutil
import psutil
import time
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

def kill_chromium_processes():
    """Kill any existing chromium processes running our app."""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['name'] and 'chromium' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if '--kiosk' in cmdline and '8050' in cmdline:
                    logging.info(f"Terminating chromium process PID {proc.info['pid']}")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
    except Exception as e:
        logging.warning(f"Error killing chromium processes: {e}")

def open_browser() -> None:
    """Find chromium-browser and open it in kiosk mode pointing at the Dash app."""
    global chromium_process, chromium_restart_count
    
    if chromium_restart_count >= MAX_CHROMIUM_RESTARTS:
        logging.error(f"Maximum chromium restart attempts ({MAX_CHROMIUM_RESTARTS}) reached. Not restarting.")
        return
    
    url = "http://127.0.0.1:8050/"
    chromium_path = shutil.which('chromium-browser')

    # Kill any existing chromium processes first
    kill_chromium_processes()
    time.sleep(2)

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
            
            # Start monitoring chromium
            Timer(10, monitor_chromium).start()
            
        except Exception as e:
            logging.error(f"Failed to launch {chromium_path}: {e}")
            logging.info("Falling back to default browser.")
            webbrowser.open(url)
    else:
        logging.warning("chromium-browser not found in PATH. Opening default browser instead.")
        webbrowser.open(url)

def monitor_chromium():
    """Monitor chromium process and restart if needed."""
    global chromium_process
    
    if not is_chromium_running():
        logging.warning("Chromium process died, attempting restart")
        open_browser()
    else:
        # Schedule next check
        Timer(30, monitor_chromium).start()

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
if __name__ == "__main__":
    logging.info("Application starting.")
    Timer(1, open_browser).start() # Open browser after 1 second
    app.run(
        debug=False,
        dev_tools_ui=False,
        dev_tools_props_check=False,
        host="0.0.0.0",
        port=8050,
    )
    # Note: The background thread in data_manager will exit automatically
    # when the main application exits because it's a daemon thread.
    # If you needed cleanup, you could call data_manager.stop() here,
    # but it's generally not required for daemon threads. 