#!/bin/bash
xrandr --output HDMI-1 --brightness 0.5
source .venv/bin/activate
python plot.py
