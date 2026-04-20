#!/bin/bash

# Change to the directory of the script
cd "$(dirname "$0")"

# Set PYTHONPATH to the current directory
export PYTHONPATH="$(pwd)"

echo "Starting Binance Gateway..."
python3 gateways/binance/run_binance.py &
GATEWAY_PID=$!

echo "Starting Engine..."
python3 engine/main.py ETHUSDT &
ENGINE_PID=$!

echo "Processes started!"
echo "Gateway PID: $GATEWAY_PID"
echo "Engine PID: $ENGINE_PID"

# Wait for both processes
wait
