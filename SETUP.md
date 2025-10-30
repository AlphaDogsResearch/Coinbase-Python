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

### Step 4: Install Nautilus Trader

```bash
# Install using pre-built wheels (no Rust compilation needed)
pip install nautilus_trader --only-binary=:all:

# This will install the latest compatible version
```

### Step 5: Verify Nautilus Installation

```bash
# Check that nautilus_trader is installed correctly
python -c "import nautilus_trader; print(f'✅ NautilusTrader {nautilus_trader.__version__}')"

# Expected output: ✅ NautilusTrader 1.220.0 (or similar)
```

### Step 6: Install All Other Dependencies

```bash
# Install all project dependencies from requirements.txt
pip install -r requirements.txt

# This installs: ccxt, pandas, numpy, matplotlib, and more
```

### Step 7: Verify Installation

```bash
# Test that all critical imports work
python -c "
import ccxt
import pandas
import numpy
import matplotlib
import nautilus_trader
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

# Install Nautilus Trader with pre-built wheels
pip install nautilus_trader --only-binary=:all:

# Verify Nautilus installation
python -c "import nautilus_trader; print(f'✅ NautilusTrader {nautilus_trader.__version__}')"

# Install all other dependencies
pip install -r requirements.txt

# Verify complete installation
python -c "from common.config_logging import to_stdout; print('✅ All dependencies ready!')"
```

## 🔧 Troubleshooting

### Issue: SSL Certificate Errors

If you see SSL errors like `SSLError(SSLCertVerificationError('OSStatus -26276'))`:

```bash
# Use trusted-host flags to bypass SSL temporarily
pip install nautilus_trader --only-binary=:all: --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org

pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org
```

**Better fix**: Install/update SSL certificates:
```bash
pip install --upgrade certifi
```

### Issue: Rust Compilation Errors

If you see errors about `cargo` or Rust compilation:

```bash
# Always use --only-binary flag for nautilus_trader
pip install nautilus_trader --only-binary=:all:
```

See `NAUTILUS_BUILD_FIX.md` for detailed troubleshooting.

### Issue: Module Not Found Errors (MOST COMMON!)

**Error**: `ModuleNotFoundError: No module named 'common'`

**Cause**: Python can't find your project modules because the project root isn't in the Python path.

**Solution 1 - Set PYTHONPATH (Recommended):**
```bash
# ALWAYS run this before starting the system
cd /Users/johannfong/Development/Coinbase-Python
export PYTHONPATH=$(pwd):$PYTHONPATH

# Then run your script
python gateways/binance/run_binance.py
```

**Solution 2 - Run with Python module flag:**
```bash
# Run from project root using -m flag
cd /Users/johannfong/Development/Coinbase-Python
python -m gateways.binance.run_binance
python -m engine.main
```

**Solution 3 - Add to shell profile (permanent):**
```bash
# Add this line to ~/.zshrc or ~/.bashrc
export PYTHONPATH="/Users/johannfong/Development/Coinbase-Python:$PYTHONPATH"

# Then reload your shell
source ~/.zshrc
```

**Pro Tip**: Create an alias in `~/.zshrc`:
```bash
alias trading="cd /Users/johannfong/Development/Coinbase-Python && source venv/bin/activate && export PYTHONPATH=\$(pwd):\$PYTHONPATH"
```

Then just run `trading` in any terminal to set everything up!

### Issue: Permission Errors

If you see permission errors when installing:

```bash
# Use --user flag (not recommended in venv)
pip install --user -r requirements.txt

# OR: Fix venv permissions
deactivate
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 🎯 Running the System

After installation, you'll need **two terminals**:

### ⚠️ IMPORTANT: Set PYTHONPATH First

The system requires the project root to be in Python's path. **Always run this before starting:**

```bash
export PYTHONPATH=$(pwd):$PYTHONPATH
```

If you skip this, you'll get: `ModuleNotFoundError: No module named 'common'`

### Terminal 1: Start the Binance Gateway

```bash
# Navigate to project root
cd /Users/johannfong/Development/Coinbase-Python

# Activate venv
source venv/bin/activate

# Set Python path (CRITICAL!)
export PYTHONPATH=$(pwd):$PYTHONPATH

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

# Set Python path (CRITICAL!)
export PYTHONPATH=$(pwd):$PYTHONPATH

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
- **nautilus_trader** - Advanced trading strategies and indicators

### Testing
- **pytest** - Unit and integration testing

## 🔄 Updating Dependencies

To update all packages:

```bash
source venv/bin/activate
pip install --upgrade -r requirements.txt
```

To update only Nautilus Trader:

```bash
pip install --upgrade nautilus_trader --only-binary=:all:
```

## 📚 Next Steps

1. **Configure API Keys**: Edit `gateways/binance/vault/binance_keys`
2. **Test the Adapter**: Run `python engine/strategies/test_integration_nautilus.py`
3. **Read Documentation**: 
   - `README.md` - Project overview
   - `NAUTILUS_ADAPTER_README.md` - Nautilus integration details
   - `TEST_COMMANDS.md` - Testing guide
4. **Run the System**: Follow the "Running the System" section above

## ⚠️ Important Notes

- **Always activate venv** before running any Python commands
- **Set PYTHONPATH** to avoid import errors
- **Use pre-built wheels** for nautilus_trader to avoid Rust compilation
- **Never commit** API keys or sensitive credentials

## 🆘 Getting Help

If you encounter issues:

1. Check `NAUTILUS_BUILD_FIX.md` for build issues
2. Check `TEST_COMMANDS.md` for testing commands
3. Verify all dependencies: `pip list`
4. Check Python version: `python --version` (should be 3.9+)

---

**System Status**: ✅ Ready to trade!

