#!/bin/bash

# Quick fix script for display access issues
echo "=== Display Fix Script ==="

# Stop the current service to break the restart loop
echo "Stopping current service..."
sudo systemctl stop plot.service 2>/dev/null || true
systemctl --user stop plot-user.service 2>/dev/null || true

# Kill any running chromium processes
echo "Killing chromium processes..."
pkill -f "chromium.*--kiosk.*8050" 2>/dev/null || true
sleep 2

# Set up display environment properly
echo "Setting up display environment..."
export DISPLAY=:0
export XAUTHORITY=$HOME/.Xauthority

# Test display access
echo "Testing display access..."
if xdpyinfo >/dev/null 2>&1; then
    echo "✓ X display is accessible"
elif xrandr >/dev/null 2>&1; then
    echo "✓ xrandr works (display is accessible)"
else
    echo "✗ Display is NOT accessible"
    echo "Trying to fix permissions..."
    
    # Try to fix X11 permissions
    xhost +local: 2>/dev/null || true
    
    # Test again
    if xrandr >/dev/null 2>&1; then
        echo "✓ Display fixed!"
    else
        echo "✗ Still cannot access display"
        echo "You may need to:"
        echo "1. Make sure you're logged into the desktop"
        echo "2. Run this script from a terminal in the desktop session"
        echo "3. Check if X11 forwarding is enabled if using SSH"
        exit 1
    fi
fi

# Check if we have a user logged into the desktop
if who | grep -q ":0"; then
    echo "✓ User is logged into desktop session"
else
    echo "⚠ Warning: No user appears to be logged into the desktop"
fi

echo ""
echo "Choose installation method:"
echo "1. User service (recommended for GUI apps)"
echo "2. System service (original method)"
echo -n "Enter choice (1 or 2): "
read choice

case $choice in
    1)
        echo "Installing as user service..."
        chmod +x install_user_service.sh
        ./install_user_service.sh
        ;;
    2)
        echo "Installing as system service..."
        chmod +x install_service.sh
        sudo ./install_service.sh
        ;;
    *)
        echo "Invalid choice. Installing as user service (default)..."
        chmod +x install_user_service.sh
        ./install_user_service.sh
        ;;
esac

echo ""
echo "=== Fix Complete ==="
echo "Run './troubleshoot.sh' to check the status" 