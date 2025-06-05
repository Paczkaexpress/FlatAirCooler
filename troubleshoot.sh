#!/bin/bash

# Troubleshooting script for FlatAirCooler application
echo "=== FlatAirCooler Troubleshooting Tool ==="
echo ""

SERVICE_NAME="plot.service"

# Function to check service status
check_service_status() {
    echo "--- Service Status ---"
    
    # Check system service
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo "✓ System service is RUNNING"
    else
        echo "✗ System service is NOT RUNNING"
    fi
    
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo "✓ System service is ENABLED (will start at boot)"
    else
        echo "✗ System service is DISABLED (will not start at boot)"
    fi
    
    # Check user service
    USER_SERVICE="plot-user.service"
    if systemctl --user is-active --quiet "$USER_SERVICE" 2>/dev/null; then
        echo "✓ User service is RUNNING"
    else
        echo "✗ User service is NOT RUNNING"
    fi
    
    if systemctl --user is-enabled --quiet "$USER_SERVICE" 2>/dev/null; then
        echo "✓ User service is ENABLED (will start at login)"
    else
        echo "✗ User service is DISABLED (will not start at login)"
    fi
    
    echo ""
}

# Function to check processes
check_processes() {
    echo "--- Running Processes ---"
    
    PYTHON_COUNT=$(pgrep -f "python.*frontend.py" | wc -l)
    echo "Python frontend processes: $PYTHON_COUNT"
    
    CHROMIUM_COUNT=$(pgrep -f "chromium.*--kiosk.*8050" | wc -l)
    echo "Chromium kiosk processes: $CHROMIUM_COUNT"
    
    if [ $PYTHON_COUNT -gt 0 ]; then
        echo "✓ Frontend is running"
    else
        echo "✗ Frontend is not running"
    fi
    
    if [ $CHROMIUM_COUNT -gt 0 ]; then
        echo "✓ Chromium is running"
    else
        echo "✗ Chromium is not running"
    fi
    echo ""
}

# Function to check network connectivity
check_network() {
    echo "--- Network Connectivity ---"
    
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo "✓ Internet connectivity OK"
    else
        echo "✗ No internet connectivity"
    fi
    
    if curl -s http://127.0.0.1:8050/ >/dev/null; then
        echo "✓ Dash app is responding on port 8050"
    else
        echo "✗ Dash app is not responding on port 8050"
    fi
    echo ""
}

# Function to check display
check_display() {
    echo "--- Display Status ---"
    
    if [ -n "$DISPLAY" ]; then
        echo "✓ DISPLAY environment variable is set: $DISPLAY"
    else
        echo "✗ DISPLAY environment variable is not set"
    fi
    
    if xrandr >/dev/null 2>&1; then
        echo "✓ X11 display is accessible"
        echo "Available outputs:"
        xrandr --listmonitors 2>/dev/null || echo "  (Unable to list monitors)"
    else
        echo "✗ X11 display is not accessible"
    fi
    echo ""
}

# Function to check bluetooth
check_bluetooth() {
    echo "--- Bluetooth Status ---"
    
    if command -v bluetoothctl >/dev/null 2>&1; then
        BT_STATUS=$(sudo systemctl is-active bluetooth 2>/dev/null || echo "inactive")
        if [ "$BT_STATUS" = "active" ]; then
            echo "✓ Bluetooth service is running"
        else
            echo "✗ Bluetooth service is not running"
        fi
    else
        echo "? Bluetooth tools not found"
    fi
    echo ""
}

# Function to show recent logs
show_logs() {
    echo "--- Recent Application Logs (last 20 lines) ---"
    if [ -f "dash_app.log" ]; then
        tail -20 dash_app.log
    else
        echo "No dash_app.log file found"
    fi
    echo ""
    
    echo "--- Recent Service Logs (last 10 lines) ---"
    echo "System service logs:"
    sudo journalctl -u "$SERVICE_NAME" --no-pager -n 5 2>/dev/null || echo "Cannot access system service logs"
    echo ""
    echo "User service logs:"
    journalctl --user -u "plot-user.service" --no-pager -n 5 2>/dev/null || echo "Cannot access user service logs"
    echo ""
}

# Function to suggest fixes
suggest_fixes() {
    echo "--- Suggested Fixes ---"
    
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "• Start the service: sudo systemctl start $SERVICE_NAME"
    fi
    
    if ! systemctl is-enabled --quiet "$SERVICE_NAME"; then
        echo "• Enable auto-start: sudo systemctl enable $SERVICE_NAME"
    fi
    
    if ! curl -s http://127.0.0.1:8050/ >/dev/null; then
        echo "• Check if Python app is running: pgrep -f frontend.py"
        echo "• Check virtual environment: source .venv/bin/activate"
        echo "• Install dependencies: pip install -r requirements.txt"
    fi
    
    if ! pgrep -f "chromium.*--kiosk.*8050" >/dev/null; then
        echo "• Install chromium: sudo apt install chromium-browser"
        echo "• Check if DISPLAY is set properly"
    fi
    
    if ! xrandr >/dev/null 2>&1; then
        echo "• Check X11 forwarding and display permissions"
        echo "• Try: export DISPLAY=:0"
    fi
    
    echo "• View detailed logs: sudo journalctl -u $SERVICE_NAME -f"
    echo "• Restart everything: sudo systemctl restart $SERVICE_NAME"
    echo ""
}

# Main execution
check_service_status
check_processes
check_network
check_display
check_bluetooth
show_logs
suggest_fixes

echo "=== Troubleshooting Complete ===" 