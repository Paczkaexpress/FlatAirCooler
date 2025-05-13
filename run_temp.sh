#!/bin/bash

# Exit on any error
set -e

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> /home/paczkaexpress/Software/FlatAirCooler/dash_app.log
}

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    log_message "Error: Virtual environment not found"
    exit 1
fi

# Wait for display to be ready (max 30 seconds)
for i in {1..30}; do
    if xrandr &>/dev/null; then
        break
    fi
    if [ $i -eq 30 ]; then
        log_message "Error: Display not ready after 30 seconds"
        exit 1
    fi
    sleep 1
done

# Set display brightness
if ! xrandr --output HDMI-1 --brightness 0.5; then
    log_message "Warning: Failed to set display brightness"
fi

# Activate virtual environment and run the application
source .venv/bin/activate
log_message "Starting frontend application"
python frontend.py
