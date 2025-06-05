#!/bin/bash

# Exit on any error
set -e

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> /home/paczkaexpress/Software/FlatAirCooler/dash_app.log
}

# Function to cleanup processes on exit
cleanup() {
    log_message "Cleanup: Terminating chromium processes"
    pkill -f "chromium.*--kiosk.*8050" 2>/dev/null || true
    pkill -f "python.*frontend.py" 2>/dev/null || true
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    log_message "Error: Virtual environment not found"
    exit 1
fi

# Setup display environment
setup_display() {
    log_message "Setting up display environment..."
    
    # Try to detect the correct DISPLAY value
    if [ -z "$DISPLAY" ]; then
        export DISPLAY=:0
        log_message "Set DISPLAY to :0"
    fi
    
    # Set XAUTHORITY if not set
    if [ -z "$XAUTHORITY" ]; then
        export XAUTHORITY=/home/paczkaexpress/.Xauthority
        log_message "Set XAUTHORITY to /home/paczkaexpress/.Xauthority"
    fi
    
    # Wait for X server to be ready
    log_message "Waiting for X server to be ready..."
    for i in {1..60}; do
        if xdpyinfo >/dev/null 2>&1; then
            log_message "X server is ready"
            break
        elif [ $i -eq 60 ]; then
            log_message "Warning: X server not ready after 60 seconds, trying xrandr..."
            if xrandr >/dev/null 2>&1; then
                log_message "xrandr works, proceeding"
                break
            else
                log_message "Error: Cannot access X display after 60 seconds"
                exit 1
            fi
        fi
        sleep 1
    done
}

# Setup display first
setup_display

# Wait for network connectivity
log_message "Checking network connectivity..."
for i in {1..30}; do
    if ping -c 1 8.8.8.8 &>/dev/null; then
        log_message "Network is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_message "Warning: Network not ready after 30 seconds, continuing anyway"
    fi
    sleep 1
done

# Set display brightness - try multiple output names
log_message "Setting display brightness..."
BRIGHTNESS_SET=false
for output in HDMI-1 HDMI-A-1 HDMI1 DP-1 VGA-1; do
    if xrandr --output $output --brightness 0.5 2>/dev/null; then
        log_message "Successfully set brightness on $output"
        BRIGHTNESS_SET=true
        break
    fi
done

if [ "$BRIGHTNESS_SET" = false ]; then
    log_message "Warning: Could not set brightness on any output"
fi

# Kill any existing chromium processes
log_message "Cleaning up existing chromium processes"
pkill -f "chromium.*--kiosk.*8050" 2>/dev/null || true
sleep 2

# Function to start chromium with monitoring
start_chromium() {
    log_message "Starting chromium browser in kiosk mode"
    
    # Wait for the Dash app to be ready
    for i in {1..30}; do
        if curl -s http://127.0.0.1:8050/ > /dev/null 2>&1; then
            log_message "Dash app is responding, starting chromium"
            break
        fi
        if [ $i -eq 30 ]; then
            log_message "Warning: Dash app not responding after 30 seconds, starting chromium anyway"
        fi
        sleep 1
    done
    
    # Test X display access before starting chromium
    if ! xdpyinfo >/dev/null 2>&1; then
        log_message "Warning: X display test failed, trying anyway"
    fi
    
    # Start chromium in background with better error handling
    log_message "Launching chromium with DISPLAY=$DISPLAY"
    chromium-browser \
        --kiosk \
        --force-dark-mode \
        --disable-restore-session-state \
        --disable-infobars \
        --disable-dev-shm-usage \
        --no-sandbox \
        --disable-gpu-sandbox \
        --disable-web-security \
        --disable-features=VizDisplayCompositor \
        --start-fullscreen \
        --window-position=0,0 \
        --no-first-run \
        --disable-default-apps \
        --disable-popup-blocking \
        --disable-translate \
        --disable-background-timer-throttling \
        --disable-backgrounding-occluded-windows \
        --disable-renderer-backgrounding \
        http://127.0.0.1:8050/ > /tmp/chromium.log 2>&1 &
    
    CHROMIUM_PID=$!
    log_message "Chromium started with PID: $CHROMIUM_PID"
    
    # Give chromium a moment to start
    sleep 3
    
    # Check if chromium actually started successfully
    if ! kill -0 $CHROMIUM_PID 2>/dev/null; then
        log_message "Error: Chromium failed to start properly"
        if [ -f /tmp/chromium.log ]; then
            log_message "Chromium error log:"
            cat /tmp/chromium.log >> /home/paczkaexpress/Software/FlatAirCooler/dash_app.log
        fi
    else
        log_message "Chromium appears to be running successfully"
    fi
}

# Function to monitor chromium process
monitor_chromium() {
    while true; do
        sleep 15  # Increased monitoring interval
        
        # Check if chromium is still running
        if ! pgrep -f "chromium.*--kiosk.*8050" > /dev/null; then
            log_message "Chromium process died, restarting..."
            
            # Add a longer delay before restart to avoid rapid cycling
            sleep 5
            start_chromium
        fi
        
        # Check if dash app is still responding
        if ! curl -s http://127.0.0.1:8050/ > /dev/null 2>&1; then
            log_message "Warning: Dash app not responding"
        fi
    done
}

# Activate virtual environment and run the application
log_message "Activating virtual environment"
source .venv/bin/activate

log_message "Starting frontend application"

# Start the Python app in background
python frontend.py &
PYTHON_PID=$!
log_message "Python frontend started with PID: $PYTHON_PID"

# Wait a moment for the app to initialize
sleep 5

# Start chromium
start_chromium

# Start chromium monitoring in background
monitor_chromium &
MONITOR_PID=$!

# Wait for the Python process to finish
wait $PYTHON_PID

# If we get here, Python process ended, so cleanup
log_message "Python process ended, cleaning up"
kill $MONITOR_PID 2>/dev/null || true
cleanup
