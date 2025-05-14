# Live Trading Bot – Core Architecture

This module defines the **abstract base classes (ABCs)** that form the backbone of a modular, real-time crypto trading bot. These interfaces allow for pluggable components to be cleanly separated, tested, and extended.

---

## 🔁 Pipeline Flow

```
MarketDataHandler
      ↓
Strategy (Signal Generation)
      ↓
PortfolioManager (Sizing + Capital + Risk Check)
      ↓
RiskManager (Optional, pluggable)
      ↓
OrderManager (Queue/Rollback/Cancel)
      ↓
TradeExecution (Live Order Placement)
      ↓
ExecutionReport + PositionTracker
```

---

## 🧩 Core Components

### `MarketDataHandler`
- **Purpose**: Fetch and normalize market data from exchanges.
- **Input**: None (internal fetch logic).
- **Output**: `dict` of structured market data per asset.

---

### `Strategy`
- **Purpose**: Analyze market data and generate trade signals.
- **Input**: Market data (`dict`).
- **Output**: Signal dictionary like `{ "BTCUSDT": "long", "ETHUSDT": "short" }`.

---

### `PortfolioManager`
- **Purpose**: Position sizing, capital allocation, and filtering trades.
- **Input**: Signals (`dict`), AUM (`float`).
- **Output**: Dict of `Order` objects keyed by asset.

---

### `RiskManager` (optional)
- **Purpose**: Validate each order against risk rules.
- **Input**: `Order`, AUM.
- **Output**: `bool` (True = allowed, False = blocked).

---

### `OrderManager`
- **Purpose**: Manage order queue, cancel unplaced trades, and track pending orders.
- **Input**: Orders (`dict`).
- **Output**: Access to queued orders (`dict`), cancellation logic.

---

### `TradeExecution`
- **Purpose**: Place live trades on an exchange.
- **Input**: Orders (`dict`).
- **Output**: None directly (trades are placed externally).

---

### `ExecutionLogger`
- **Purpose**: Log each trade’s outcome.
- **Input**: `Order`, status string, fill price (optional).
- **Output**: Logging side-effect.

---

### `PositionTracker`
- **Purpose**: Maintain current positions and PnL tracking.
- **Input**: Executed `Order`, fill price.
- **Output**: Internal state; exposes `get_positions()` and `get_pnl()`.

---

### `Order`
- **Dataclass**
- Fields: `asset`, `quantity`, `price` (optional), `order_type` (default: "market").

---

## ✅ How to Use

1. Implement each abstract class in its own module.
2. Wire them together in an orchestrator (e.g., `main.py`).
3. Swap out components (e.g. `MockExecution` vs `BinanceExecution`) with zero friction.

---

## 📂 Directory

This `core/` module contains only the interface definitions. Concrete implementations should live in folders like `strategies/`, `execution/`, `portfolio/`, etc.

