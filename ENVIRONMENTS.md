# Multi-Environment Configuration Guide

This guide explains how to manage **development**, **testnet**, and **production** environments for your trading system.

---

## 📋 Environment Overview

| Environment | Purpose | Real Money? | API Keys | Use Case |
|-------------|---------|-------------|----------|----------|
| **Development** | Local testing | ❌ No | Not needed | Code development, unit tests, backtesting |
| **Testnet** | Pre-production | ❌ No (fake) | Testnet keys | Strategy validation, integration testing |
| **Production** | Live trading | ✅ **YES** | Production keys | Real trading with actual funds |

---

## 🔧 Setup Instructions

### 1. Choose Your Environment Template

Copy the appropriate template based on your needs:

```bash
cd /Users/johannfong/Development/Coinbase-Python

# For development
cp env.development.example .env

# For testnet
cp env.testnet.example .env

# For production (⚠️ BE CAREFUL!)
cp env.production.example .env
```

### 2. Edit Configuration

```bash
nano .env
```

Customize the values for your environment:
- `TRADE_UNIT`: Position size multiplier
- `LOG_LEVEL`: Logging verbosity
- API endpoints (testnet/production only)

### 3. Secure API Keys (Testnet & Production Only)

API keys are stored separately from `.env`:

```bash
# For testnet
nano gateways/binance/vault/binance_keys

# Add your keys:
API_KEY=your_testnet_or_production_api_key
API_SECRET=your_testnet_or_production_api_secret
```

⚠️ **NEVER commit API keys to git!**

---

## 🚀 Running Different Environments

### Development Mode

```bash
cd /Users/johannfong/Development/Coinbase-Python
cp env.development.example .env

# Activate environment
source venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH

# Run with development config
python engine/main.py ETHUSDT
```

**What happens:**
- `TRADE_UNIT=1.0` (minimum position sizes)
- `LOG_LEVEL=DEBUG` (detailed logs)
- Uses mock/simulated data
- No real API calls
- Safe for experimentation

---

### Testnet Mode

```bash
cd /Users/johannfong/Development/Coinbase-Python
cp env.testnet.example .env

# Edit .env and configure testnet settings
nano .env

# Setup testnet API keys
nano gateways/binance/vault/binance_keys
# Add your TESTNET keys (get from https://testnet.binancefuture.com)

# Run gateway (Terminal 1)
source venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH
python gateways/binance/run_binance.py

# Run engine (Terminal 2)
source venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH
python engine/main.py ETHUSDT
```

**What happens:**
- `TRADE_UNIT=2.0` (moderate testing)
- `LOG_LEVEL=INFO` (clean logs)
- Connects to Binance testnet
- Uses FAKE testnet USDT
- Real-time market data
- No financial risk

**Testnet Resources:**
- Get testnet keys: https://testnet.binancefuture.com
- Fund testnet account: Use faucet on testnet site
- Testnet explorer: https://testnet.binancefuture.com/en/futures/BTCUSDT

---

### Production Mode (⚠️ LIVE TRADING)

```bash
cd /Users/johannfong/Development/Coinbase-Python
cp env.production.example .env

# ⚠️ CAREFULLY edit production config
nano .env

# ⚠️ Setup PRODUCTION API keys
nano gateways/binance/vault/binance_keys
# Add your PRODUCTION keys (get from https://www.binance.com)

# Double-check configuration
cat .env | grep -E "ENVIRONMENT|TRADE_UNIT|USE_LIVE_TRADING"

# Run gateway (Terminal 1)
source venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH
python gateways/binance/run_binance.py

# Run engine (Terminal 2)
source venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH
python engine/main.py ETHUSDT
```

**What happens:**
- `TRADE_UNIT=1.0` (conservative start)
- `LOG_LEVEL=INFO` (production logs)
- Connects to Binance MAINNET
- Uses REAL money
- **⚠️ FINANCIAL RISK**

---

## 🔐 Security Best Practices

### API Key Management

1. **Use separate keys for each environment**
   ```
   Testnet API Key  → testnet.binancefuture.com
   Production API Key → binance.com
   ```

2. **Configure API key permissions correctly**
   - ✅ Enable: "Enable Reading", "Enable Futures Trading"
   - ❌ Disable: "Enable Withdrawals"
   - Use IP whitelist restrictions

3. **Never commit keys to git**
   ```bash
   # .gitignore already includes:
   .env
   .env.*
   **/vault/*_keys
   ```

### File Structure

```
Coinbase-Python/
├── .env                          # Active config (gitignored)
├── env.development.example       # Development template (committed)
├── env.testnet.example          # Testnet template (committed)
├── env.production.example       # Production template (committed)
└── gateways/binance/vault/
    └── binance_keys             # API keys (gitignored)
```

---

## 📊 Environment Comparison

### Trade Unit Recommendations

| Environment | Recommended TRADE_UNIT | Example Order Size (ETHUSDT) | USD Value @ $4,100/ETH |
|-------------|------------------------|------------------------------|------------------------|
| Development | `1.0` | 0.005 ETH | ~$20 |
| Testnet | `1.0` - `5.0` | 0.005 - 0.025 ETH | ~$20 - $100 |
| Production | `1.0` (start small!) | 0.005 ETH | ~$20 |

⚠️ **Production**: Start with `TRADE_UNIT=1.0` and gradually increase after validating performance!

### Logging Levels

| Environment | Recommended LOG_LEVEL | Output Volume | Use Case |
|-------------|-----------------------|---------------|----------|
| Development | `DEBUG` | High | Troubleshooting, development |
| Testnet | `INFO` or `DEBUG` | Medium-High | Validation, debugging |
| Production | `INFO` | Medium | Monitoring, alerts |
| Production (stable) | `WARNING` | Low | Reduce noise |

---

## 🧪 Testing Workflow

**Recommended progression:**

```
1. Development (CSV/Mock Data)
   ↓ Verify: Logic works correctly
   
2. Testnet (Fake Money)
   ↓ Verify: Orders execute, positions track correctly
   
3. Production (⚠️ Real Money)
   ↓ Monitor: Performance, fills, P&L
```

### Never skip testnet!

**Testnet validates:**
- ✅ API integration works
- ✅ Orders execute correctly
- ✅ Position tracking accurate
- ✅ Risk management functions
- ✅ Strategy signals trigger properly
- ✅ No code errors under load

---

## 🔄 Switching Environments

### Quick Switch Method

Keep multiple `.env` files:

```bash
# Save current environment
cp .env .env.current

# Switch to testnet
cp env.testnet.example .env
nano .env  # Edit as needed

# Switch to production
cp env.production.example .env
nano .env  # Edit as needed

# Switch back
cp .env.current .env
```

### Validation

Before running, always verify your environment:

```bash
# Check environment setting
cat .env | grep ENVIRONMENT

# Check trade unit
cat .env | grep TRADE_UNIT

# Check if live trading
cat .env | grep USE_LIVE_TRADING

# Verify it loaded correctly
python engine/main.py ETHUSDT 2>&1 | head -20
# Look for:
# "Logging configured with level: INFO"
# "Trade unit configured: 1.0"
```

---

## ⚠️ Common Pitfalls

### 1. **Using production keys in development**
**Problem:** Accidentally live trading while developing  
**Solution:** Use separate API keys, keep keys in separate vault files

### 2. **Large TRADE_UNIT in production**
**Problem:** First production order is too large  
**Solution:** Always start with `TRADE_UNIT=1.0`

### 3. **Forgetting initialization time**
**Problem:** Strategies like PPO take 205+ hours to initialize  
**Solution:** Review initialization times, consider starting on testnet days before production

### 4. **Not monitoring initially**
**Problem:** Production issues go unnoticed  
**Solution:** Use `LOG_LEVEL=DEBUG` for first few days, enable Telegram alerts

---

## 📱 Monitoring & Alerts

### Telegram Alerts (Production Recommended)

Configure in: `engine/vault/telegram_keys`

```bash
nano engine/vault/telegram_keys

# Add:
API_KEY=your_telegram_bot_api_key
USER_ID=your_telegram_user_id
```

Get alerts for:
- Order fills
- Position changes
- Errors
- Large losses

---

## 🎯 Strategy Initialization Times

All strategies use **1-hour candles** in production:

| Strategy | Period (bars) | Time to Initialize | Notes |
|----------|---------------|-------------------|-------|
| ROC | 22 | 22 hours | ~1 day |
| CCI | 14 | 14 hours | ~14 hours |
| APO | 122 | **122 hours** | ⚠️ **5+ days** |
| PPO | 205 | **205 hours** | ⚠️ **8+ days** |
| ADX | 22 | 22 hours | ~1 day |

**Production tip:** Start system early (e.g., Friday evening) so APO/PPO are ready by next week!

---

## 📖 Summary

✅ **Development**: Safe local testing, no API keys  
✅ **Testnet**: Pre-production validation, fake money  
✅ **Production**: Live trading, real money, be careful!

**Golden Rule:** Never skip testnet before going to production!

---

📚 **Related Docs:**
- `ENV_CONFIG.md` - Detailed environment variable reference
- `SETUP.md` - Installation and setup
- `QUICKSTART.md` - Daily usage commands

