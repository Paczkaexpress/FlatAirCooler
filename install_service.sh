#!/bin/bash

# Script to install and configure the temperature plot service
# Exit on any error
set -e

# Configuration
SERVICE_NAME="plot.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
CURRENT_USER=$(whoami)
PROJECT_DIR=$(pwd)

echo "Installing temperature plot service..."
echo "Current user: $CURRENT_USER"
echo "Project directory: $PROJECT_DIR"

# Make run script executable
chmod +x "$PROJECT_DIR/run_temp.sh"
echo "Made run_temp.sh executable"

# Copy service file to systemd directory
echo "Installing service file to $SERVICE_FILE"
sudo cp "$PROJECT_DIR/$SERVICE_NAME" "$SERVICE_FILE"

# Update service file paths if needed
sudo sed -i "s|/home/paczkaexpress/Software/FlatAirCooler|$PROJECT_DIR|g" "$SERVICE_FILE"
sudo sed -i "s|User=paczkaexpress|User=$CURRENT_USER|g" "$SERVICE_FILE"
sudo sed -i "s|Group=paczkaexpress|Group=$CURRENT_USER|g" "$SERVICE_FILE"
sudo sed -i "s|HOME=/home/paczkaexpress|HOME=$HOME|g" "$SERVICE_FILE"

# Set proper permissions
sudo chmod 644 "$SERVICE_FILE"

# Reload systemd configuration
sudo systemctl daemon-reload
echo "Systemd configuration reloaded"

# Enable the service to start at boot
sudo systemctl enable "$SERVICE_NAME"
echo "Service enabled for auto-start at boot"

# Check if service is already running and stop it
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Service is currently running. Stopping it..."
    sudo systemctl stop "$SERVICE_NAME"
fi

# Start the service
echo "Starting the service..."
sudo systemctl start "$SERVICE_NAME"

# Check service status
echo ""
echo "Service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "Installation complete!"
echo ""
echo "Useful commands:"
echo "  Check status:    sudo systemctl status $SERVICE_NAME"
echo "  Stop service:    sudo systemctl stop $SERVICE_NAME" 
echo "  Start service:   sudo systemctl start $SERVICE_NAME"
echo "  Restart service: sudo systemctl restart $SERVICE_NAME"
echo "  View logs:       sudo journalctl -u $SERVICE_NAME -f"
echo "  Disable service: sudo systemctl disable $SERVICE_NAME" 