import logging
import subprocess
import webbrowser
import shutil
from threading import Timer

import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate
import plotly.graph_objs as go

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

# ────────────────────────────────────────────────────────────────────────────────
# DATA MANAGER INITIALIZATION
# ────────────────────────────────────────────────────────────────────────────────

# Instantiate the DataManager
data_manager = DataManager()

# Start the background data collection
data_manager.start()

# ────────────────────────────────────────────────────────────────────────────────
# DASH APP INITIALISATION
# ────────────────────────────────────────────────────────────────────────────────
app = dash.Dash(__name__, assets_folder='assets')

# --- Helper for Browser --- (Moved from plot.py)
def open_browser() -> None:
    """Find chromium-browser and open it in kiosk mode pointing at the Dash app."""
    url = "http://127.0.0.1:8050/"
    chromium_path = shutil.which('chromium-browser') # Find chromium-browser in PATH

    if chromium_path:
        logging.info(f"Found chromium-browser at: {chromium_path}")
        try:
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
            logging.info(f"Launched {chromium_path} in kiosk mode.")
        except Exception as e:
            logging.error(f"Failed to launch {chromium_path}: {e}")
            logging.info("Falling back to default browser.")
            webbrowser.open(url) # Fallback
    else:
        logging.warning("chromium-browser not found in PATH. Opening default browser instead.")
        webbrowser.open(url) # Fallback if chromium not found

# --- Blank Figure --- (Moved from plot.py)
blank_fig = go.Figure()
blank_fig.update_layout(
    paper_bgcolor="#000000",
    plot_bgcolor="#000000",
    xaxis_visible=False,
    yaxis_visible=False,
    margin=dict(l=0, r=0, t=0, b=0),
)

# ────────────────────────────────────────────────────────────────────────────────
# DASH LAYOUT (Moved from plot.py)
# ────────────────────────────────────────────────────────────────────────────────
app.layout = html.Div(
    [
        dcc.Graph(
            id="live-graph",
            figure=blank_fig,
            style={"height": "100vh", "width": "100vw"},
            config={"displayModeBar": False},
        ),
        dcc.Interval(id="interval", interval=(data_manager.get_measurement_interval_sec() + 5) * 1000, n_intervals=0),
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
    current_data = data_manager.get_data()

    if current_data.empty:
        return blank_fig

    try:
        fig = go.Figure()

        # Define traces, separating Wroclaw for secondary axis
        sensor_traces = [
            ("Sens1", "Poddasze"),
            ("Sens2", "Kuchnia"),
            ("Sens3", "Pokój Maksia"),
        ]
        weather_trace = ("Wroclaw", "Wrocław")

        # Add sensor traces to the primary y-axis
        for col, name in sensor_traces:
            if col in current_data.columns:
                trace_data = current_data[['Timestamp', col]].dropna()
                if not trace_data.empty:
                    fig.add_trace(go.Scatter(
                        x=trace_data['Timestamp'],
                        y=trace_data[col],
                        mode='lines+markers',
                        name=name,
                        yaxis='y1' # Explicitly assign to primary axis
                    ))

        # Add weather trace to the secondary y-axis
        col, name = weather_trace
        if col in current_data.columns:
            trace_data = current_data[['Timestamp', col]].dropna()
            if not trace_data.empty:
                fig.add_trace(go.Scatter(
                    x=trace_data['Timestamp'],
                    y=trace_data[col],
                    mode='lines', # Maybe lines only for weather?
                    name=name,
                    yaxis='y2' # Assign to secondary axis
                ))

        # Update layout to include the secondary y-axis
        fig.update_layout(
            title="Live Temperature Readings",
            xaxis_title="Timestamp",
            yaxis=dict( # Primary Y-axis (Sensors)
                title=dict( # Title dictionary
                    text="°C (Sensors)",
                    font=dict(color="#1f77b4") # Font settings inside title
                ),
                tickfont=dict(color="#1f77b4")
            ),
            yaxis2=dict( # Secondary Y-axis (Weather)
                title=dict( # Title dictionary
                    text="°C (Wrocław)",
                    font=dict(color="#ff7f0e") # Font settings inside title
                ),
                overlaying="y",
                side="right",
                showgrid=False, # Often good to hide grid for secondary axis
                tickfont=dict(color="#ff7f0e")
            ),
            template="plotly_dark",
            uirevision=True, # Keep zoom level etc.
            paper_bgcolor="#000000",
            plot_bgcolor="#000000",
            legend=dict(
                orientation="h",
                y=-0.25, # Adjust if needed
                x=0.5,
                xanchor="center",
            ),
            legend_font_size=18,
            margin=dict(l=40, r=40, t=40, b=80, pad=0), # Adjusted margins for axis titles
        )

        return fig
    except Exception as e:
        logging.error(f"Error updating graph: {e}")
        return blank_fig


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