#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e
# Treat unset variables as an error when substituting.
set -u
# Pipelines fail if any command in the pipeline fails
set -o pipefail

# --- Configuration ---
VENV_DIR=".venv"
REQUIREMENTS_FILE="requirements.txt"
# System dependencies needed for bluepy and potentially other requirements
SYSTEM_DEPS="python3-pip libglib2.0-dev libbluetooth-dev pkg-config chromium-browser"

# --- Script Start ---
echo "Starting setup for FlatAirCooler..."

# 1. Install System Dependencies
echo "Updating package list and installing system dependencies ($SYSTEM_DEPS)..."
sudo apt-get update
sudo apt-get install -y $SYSTEM_DEPS
echo "System dependencies installed."

# 2. Create Virtual Environment (if it doesn't exist)
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python virtual environment in '$VENV_DIR'..."
  python3 -m venv "$VENV_DIR"
  echo "Virtual environment created."
else
  echo "Virtual environment '$VENV_DIR' already exists."
fi

# 3. Install Python Dependencies
echo "Installing Python requirements from '$REQUIREMENTS_FILE' into the virtual environment..."
# Ensure we use the pip from the virtual environment
"$VENV_DIR/bin/pip" install -r "$REQUIREMENTS_FILE"
echo "Python requirements installed."

# --- Script End ---
echo ""
echo "Setup complete!"
echo "Before running the application, remember to:"
echo "  1. Activate the virtual environment: source $VENV_DIR/bin/activate"
echo "  2. Configure API keys and device MACs in plot.py"
echo "  3. Run the application: python plot.py"

exit 0 