#!/bin/bash
# Coinbase-Python Trading System Startup Script

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set PYTHONPATH to project root
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Print status
echo "✅ Environment configured:"
echo "   PYTHONPATH: $PYTHONPATH"
echo "   Virtual env: activated"
echo ""
echo "You can now run:"
echo "   python engine/main.py ETHUSDT"
echo "   python gateways/binance/run_binance.py"
echo ""

# Keep shell open with configured environment
exec $SHELL
