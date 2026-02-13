# Setup Guide - Coinbase Trading System

This guide walks you through setting up your Python trading system from scratch.

## Prerequisites

- Python 3.9 or higher
- macOS/Linux (Windows users: use WSL or adjust commands)
- Git (to clone the repository)

## 🚀 Quick Start Installation

### Step 1: Navigate to Project Directory

```bash
cd .../Coinbase-Python
```

### Step 2: Create Virtual Environment (First Time Only)

```bash
# Create a new virtual environment
python3 -m venv venv

# You only need to do this once
```

### Step 3: Activate Virtual Environment

```bash
# Activate the venv (do this every time you open a new terminal)
source venv/bin/activate

# You should see (venv) in your terminal prompt
```

### Step 4: Install All Dependencies

```bash
# Install all project dependencies from requirements.txt
pip install -r requirements.txt

# This installs: ccxt, pandas, numpy, matplotlib, and more
```

### Step 5: Verify Installation

```bash
# Test that all critical imports work
python -c "
import ccxt
import pandas
import numpy
import matplotlib
from common.config_logging import to_stdout
print('✅ All dependencies installed successfully!')
"
```

## 📋 Complete Installation Command Sequence

For convenience, here's the complete sequence in one block:

```bash
# Navigate to project
cd /Users/johannfong/Development/Coinbase-Python

# Activate venv (create it first if it doesn't exist: python3 -m venv venv)
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt

# Verify complete installation
python -c "from common.config_logging import to_stdout; print('✅ All dependencies ready!')"
```

## 🔧 Troubleshooting

### Issue: SSL Certificate Errors

If you see SSL errors like `SSLError(SSLCertVerificationError('OSStatus -26276'))`:

```bash
# Use trusted-host flags to bypass SSL temporarily
pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org
```

**Better fix**: Install/update SSL certificates:
```bash
pip install --upgrade certifi
```

### Issue: Module Not Found Errors

**Error**: `ModuleNotFoundError: No module named 'common'`

**Cause**: Python can't find your project modules because the project root isn't in the Python path.

**Solution**: The scripts now automatically add the project root to the Python path. Just run them from anywhere:

```bash
# These will work from any directory
python engine/main.py ETHUSDT
python gateways/binance/run_binance.py
```

If you still encounter issues, you can manually set PYTHONPATH:

```bash
# Run from project root
cd /Users/johannfong/Development/Coinbase-Python
export PYTHONPATH=$(pwd):$PYTHONPATH

# Then run your script
python engine/main.py ETHUSDT
```

**Pro Tip**: Create an alias in `~/.zshrc`:
```bash
alias trading="cd /Users/johannfong/Development/Coinbase-Python && source venv/bin/activate && export PYTHONPATH=\$(pwd):\$PYTHONPATH"
```

Then just run `trading` in any terminal to set everything up!

### Issue: Permission Errors

If you see permission errors when installing:

```bash
# Fix venv permissions
deactivate
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 🎯 Running the System

After installation, you'll need **two terminals**:

### Terminal 1: Start the Binance Gateway

```bash
# Navigate to project root
cd /Users/johannfong/Development/Coinbase-Python

# Activate venv
source venv/bin/activate

# Start gateway
python gateways/binance/run_binance.py
```

This connects to Binance and streams market data.

### Terminal 2: Start the Trading Engine

```bash
# Navigate to project root
cd /Users/johannfong/Development/Coinbase-Python

# Activate venv
source venv/bin/activate

# Start engine with your chosen symbol
python engine/main.py ETHUSDT  # Available: ETHUSDT, BTCUSDT, XRPUSDT
```

**Available Symbols:**
- `ETHUSDT` - Ethereum/USDT pair (currently active)
- `BTCUSDT` - Bitcoin/USDT pair
- `XRPUSDT` - Ripple/USDT pair

*(Configure symbols in `common/config_symbols.py`)*

This runs your trading strategies and manages orders for the specified symbol.

## 📦 What's Installed?

After running `pip install -r requirements.txt`, you'll have:

### Core Dependencies
- **ccxt** - Exchange connectivity (Binance, Coinbase, etc.)
- **python-dotenv** - Environment variable management
- **websockets** - WebSocket connections for real-time data
- **requests** - HTTP requests

### Data & Analysis
- **pandas** - Data manipulation and analysis
- **numpy** - Numerical computing
- **matplotlib** - Visualization and plotting

### Trading Framework
- **In-house strategies** - Custom trading strategies and indicators

### Testing
- **pytest** - Unit and integration testing

## 🔄 Updating Dependencies

To update all packages:

```bash
source venv/bin/activate
pip install --upgrade -r requirements.txt
```

## 📚 Next Steps

1. **Configure API Keys**: Edit `gateways/binance/vault/binance_keys`
2. **Run Backtests**: Run `python -m engine.backtest.backtest_runner --config engine/backtest/configs/simple_order_csv.json`
3. **Read Documentation**: 
   - `README.md` - Project overview
   - `TEST_COMMANDS.md` - Testing guide
4. **Run the System**: Follow the "Running the System" section above

## ⚠️ Important Notes

- **Always activate venv** before running any Python commands
- **Scripts auto-configure paths** - no need to manually set PYTHONPATH
- **Never commit** API keys or sensitive credentials

## 🆘 Getting Help

If you encounter issues:

1. Verify all dependencies: `pip list`
2. Check Python version: `python --version` (should be 3.9+)
3. Check that venv is activated: look for `(venv)` in your prompt

---

**System Status**: ✅ Ready to trade!
