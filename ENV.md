# Environment Configuration - Simple Guide

## Quick Setup

### 1. Choose Your Environment

```bash
cd /Users/johannfong/Development/Coinbase-Python

# Development (fast testing with 1-second candles)
cp env.development.example .env

# Testnet (realistic testing with 1-hour candles)
cp env.testnet.example .env

# Production (⚠️ LIVE TRADING with 1-hour candles)
cp env.production.example .env
```

### 2. Run

```bash
export PYTHONPATH=$(pwd):$PYTHONPATH
source venv/bin/activate
python engine/main.py ETHUSDT
```

---

## Environment Variables

### Required Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `ENVIRONMENT` | `development`, `testnet`, `production` | `development` | Environment name |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `DEBUG` | Logging verbosity |
| `TEST_INTERVAL` | `1` or `3600` (seconds) | `1` | Candle interval (development only) |
| `ENABLE_TRACE` | `true`, `false` | `false` | Enable CSV trace logging for strategy auditing |

---

## Logging Levels & Strategy Behavior

### DEBUG (Development Default)
Shows detailed bar-by-bar processing for debugging:
- **Bar feeds**: `📊 Feeding bar to Nautilus: Bar(O=4124.34 H=4124.34 L=4124.34 C=4124.34)`
- **on_bar execution**: `✅ Nautilus strategy.on_bar() executed`
- **Indicator updates**: `📈 ROC Indicator: value=-0.0365, initialized=True, period=22`
- **Internal operations**: Indicator calculations, conversions

**Use for**: Development, troubleshooting, understanding strategy behavior

### INFO (Testnet/Production Default)
Shows only important trading actions and decisions:
- **Entry signals**: 
  ```
  🟢 LONG ENTRY | ROC oversold recovery
     Price: 4124.34 | Qty: 1.0000 | SL: 4037.73
     ROC: -3.65 | ROC Period: 22
  ```
- **Exit signals**:
  ```
  🟡 LONG EXIT: ROC returned to midpoint | Price: 4130.50
  ```
- **Order execution**: `Intercepted order submission: MARKET order, BUY, Quantity=1.000`
- **Position changes**: `New Position for Strategy: BUY: 0.005`

**Use for**: Production monitoring, clean operational logs

### WARNING
Only warnings and issues:
- Failed conversions
- Missing data
- Strategy warnings

**Use for**: Stable production with minimal logging

### ERROR
Only errors and critical issues:
- Connection failures
- Order rejections
- System errors

**Use for**: Production with very minimal logging

---

## Trace Logging (Strategy Auditing)

When `ENABLE_TRACE=true`, the ROC strategy generates detailed CSV files in `reports/` folder containing:
- Every bar's OHLCV data
- ROC indicator values (current and previous)
- Position state and bars held
- Entry/exit conditions (True/False)
- Actions taken (ENTER_LONG, ENTER_SHORT, EXIT_LONG, EXIT_SHORT)
- Entry prices, stop loss levels, exit prices

**File format**: `roc_mean_reversion_trace_YYYYMMDD_HHMMSS.csv`

**Use for**: 
- Auditing strategy decisions
- Post-trade analysis
- Debugging unexpected behavior
- Regulatory compliance

**Note**: 
- Only ROC strategy has trace logging (CCI, APO, PPO, ADX do not)
- All timestamps are in UTC
- Disabled by default (false) for performance
- Files can grow large with 1-second candles

**Example trace CSV content**:
```csv
timestamp,bar_index,open,high,low,close,roc_value,position_state,action_taken,entry_price,stop_loss_price
1761698770000000000,4,4123.92,4124.26,4123.92,4124.26,0.0548,flat,ENTER_SHORT,4124.26,4210.87
```

---

## How It Works

### Development Mode
```bash
ENVIRONMENT=development
LOG_LEVEL=DEBUG
TEST_INTERVAL=1
```

**Behavior:**
- Uses `TEST_INTERVAL` value (1-second candles for fast testing)
- DEBUG logging enabled (detailed logs)
- No real trading

### Testnet Mode
```bash
ENVIRONMENT=testnet
LOG_LEVEL=INFO
TEST_INTERVAL=3600  # Ignored - always uses 3600
```

**Behavior:**
- **Always uses 1-hour candles** (ignores TEST_INTERVAL)
- INFO logging (cleaner logs)
- Fake money trading on Binance testnet

### Production Mode
```bash
ENVIRONMENT=production
LOG_LEVEL=INFO
TEST_INTERVAL=3600  # Ignored - always uses 3600
```

**Behavior:**
- **Always uses 1-hour candles** (ignores TEST_INTERVAL)
- INFO logging
- ⚠️ **REAL MONEY TRADING**

---

## Key Logic in main.py

```python
if environment == "development":
    interval_seconds = int(os.getenv("TEST_INTERVAL", "1"))  # Use TEST_INTERVAL
else:
    interval_seconds = 3600  # Always 1-hour for testnet/production
```

**Result:**
- **Development**: Fast testing with 1-second candles
- **Testnet/Production**: Realistic trading with 1-hour candles

---

## Strategy Initialization Times

With **1-second candles** (development):
- ROC: 22 seconds
- CCI: 14 seconds
- APO: 122 seconds (~2 minutes)
- PPO: 205 seconds (~3.5 minutes)
- ADX: 22 seconds

With **1-hour candles** (testnet/production):
- ROC: 22 hours (~1 day)
- CCI: 14 hours
- APO: 122 hours (~5 days)
- PPO: 205 hours (~8.5 days)
- ADX: 22 hours (~1 day)

---

## Examples

### Fast Development Testing
```bash
# .env
ENVIRONMENT=development
LOG_LEVEL=DEBUG
TEST_INTERVAL=1
ENABLE_TRACE=false

# Strategies ready in seconds!
# ROC: 22 seconds
# CCI: 14 seconds
```

### Development with Trace Auditing
```bash
# .env
ENVIRONMENT=development
LOG_LEVEL=DEBUG
TEST_INTERVAL=1
ENABLE_TRACE=true

# Generates CSV audit trail in reports/
# roc_mean_reversion_trace_YYYYMMDD_HHMMSS.csv
```

### Realistic Testnet Testing
```bash
# .env
ENVIRONMENT=testnet
LOG_LEVEL=INFO
TEST_INTERVAL=3600

# Strategies ready in hours (realistic)
# ROC: 22 hours
# CCI: 14 hours
```

### Production Trading
```bash
# .env
ENVIRONMENT=production
LOG_LEVEL=INFO
TEST_INTERVAL=3600

# ⚠️ Real money, 1-hour candles
# Start system early - APO takes 5+ days!
```

---

## Verification

Check your configuration on startup:

```
Logging configured with level: DEBUG
Environment: development
Candle interval: 1 seconds (1-second)
Trade unit: 1.0
```

---

## Summary

✅ **Development**: `TEST_INTERVAL=1` → Fast testing  
✅ **Testnet/Production**: Always 1-hour candles (safe & realistic)  
✅ **No manual switching needed** - environment controls everything!

