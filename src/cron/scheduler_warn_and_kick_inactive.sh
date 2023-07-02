#!/bin/bash

# Get the current day of the month
day=$(date +%d)

# If the current day is 1, start the Python script
if [ $day -eq 1 ]; then
    python3 users_warn_and_kick_inactive.py
fi
