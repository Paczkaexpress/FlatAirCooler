#!/bin/bash

# Script to install and configure the temperature plot service as a USER service
# This is better for GUI applications than system services
set -e

SERVICE_NAME="plot-user.service"
CURRENT_USER=$(whoami)
PROJECT_DIR=$(pwd)
USER_SERVICE_DIR="$HOME/.config/systemd/user"

echo "Installing temperature plot service as USER service..."
echo "Current user: $CURRENT_USER"
echo "Project directory: $PROJECT_DIR"

# Create user systemd directory if it doesn't exist
mkdir -p "$USER_SERVICE_DIR"
echo "Created user systemd directory: $USER_SERVICE_DIR"

# Make run script executable
chmod +x "$PROJECT_DIR/run_temp.sh"
echo "Made run_temp.sh executable"

# Copy service file to user systemd directory
echo "Installing service file to $USER_SERVICE_DIR/$SERVICE_NAME"
cp "$PROJECT_DIR/$SERVICE_NAME" "$USER_SERVICE_DIR/$SERVICE_NAME"

# Update service file paths to use actual paths instead of placeholders
sed -i "s|%h/Software/FlatAirCooler|$PROJECT_DIR|g" "$USER_SERVICE_DIR/$SERVICE_NAME"

# Reload user systemd configuration
systemctl --user daemon-reload
echo "User systemd configuration reloaded"

# Stop any existing system service
if systemctl is-active --quiet plot.service 2>/dev/null; then
    echo "Stopping existing system service..."
    sudo systemctl stop plot.service
    sudo systemctl disable plot.service 2>/dev/null || true
fi

# Stop existing user service if running
if systemctl --user is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Stopping existing user service..."
    systemctl --user stop "$SERVICE_NAME"
fi

# Enable the user service to start at login
systemctl --user enable "$SERVICE_NAME"
echo "User service enabled for auto-start at login"

# Enable lingering for the user (allows user services to start without login)
sudo loginctl enable-linger "$CURRENT_USER"
echo "Enabled lingering for user $CURRENT_USER"

# Start the service
echo "Starting the user service..."
systemctl --user start "$SERVICE_NAME"

# Check service status
echo ""
echo "Service status:"
systemctl --user status "$SERVICE_NAME" --no-pager

echo ""
echo "Installation complete!"
echo ""
echo "Useful commands for USER services:"
echo "  Check status:    systemctl --user status $SERVICE_NAME"
echo "  Stop service:    systemctl --user stop $SERVICE_NAME" 
echo "  Start service:   systemctl --user start $SERVICE_NAME"
echo "  Restart service: systemctl --user restart $SERVICE_NAME"
echo "  View logs:       journalctl --user -u $SERVICE_NAME -f"
echo "  Disable service: systemctl --user disable $SERVICE_NAME"
echo ""
echo "Note: This service runs in your user session and has better access to GUI components." 