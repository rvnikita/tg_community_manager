#!/bin/bash

echo "Starting the scheduler script."

# Get the current day of the month
day=$(date +%d)

echo "Current day is: $day"

# If the current day is 1, start the Python script
if [ $day -eq 12 ]; then
    echo "Executing the Python script."
    python3 ./src/cron/users_warn_and_kick_inactive.py
else
    echo "Not the 12th day. Skipping the Python script."
fi
