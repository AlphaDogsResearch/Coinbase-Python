# Nautilus Trader - Rust Build Issue Fix

## Problem

When installing `nautilus_trader` on macOS (especially Apple Silicon), you may encounter this error:

```
ld: symbol(s) not found for architecture arm64
error: could not compile `nautilus-cryptography` (lib)
RuntimeError: Error running cargo
```

**Root Cause**: Architecture mismatch between Python (x86_64) and Rust compiler (arm64).

## ✅ Solution

**Use pre-built binary wheels instead of building from source:**

```bash
pip install nautilus_trader --only-binary=:all:
```

## Installation Steps

```bash
# 1. Activate your virtual environment
source venv/bin/activate

# 2. Install using pre-built wheels only (no Rust compilation)
pip install nautilus_trader --only-binary=:all:

# 3. Verify installation
python -c "import nautilus_trader; print(f'✅ NautilusTrader {nautilus_trader.__version__}')"

pip install -r requirements.txt
```

## Upgrading

```bash
pip install --upgrade nautilus_trader --only-binary=:all:
```

## Why This Works

- Skips Rust/Cargo compilation entirely
- Uses pre-built wheels from PyPI that are already compiled for your platform
- Avoids architecture mismatch issues
- Much faster installation

## Current Version

This project uses: `nautilus_trader>=1.190.0` (currently installed: 1.220.0)

