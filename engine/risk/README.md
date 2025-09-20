# Risk Management Module

This module provides institutional-grade risk management for the Coinbase-Python trading system. It is responsible for enforcing risk controls, tracking positions, and ensuring the safety and compliance of all trading activity.

## Key Components

- **risk_manager.py**: The main risk logic. Performs checks for order size, position limits, leverage, open order count, daily loss, VaR, and cumulative loss liquidation. Integrates with the rest of the system to block or allow orders.
- **position_tracker.py**: Tracks all open positions, open orders, and PnL per symbol. Persists state to disk for recovery after restarts. Cleans up state when positions are closed.
- **portfolioValueAtRisk.py**: (Optional) Provides Value-at-Risk (VaR) calculations for portfolio-level risk.

## Features

- Order validation against multiple risk parameters
- Automatic liquidation of all positions if cumulative loss exceeds threshold
- Daily loss reset at 8am US/Eastern (with daylight savings)
- Persistent position and order tracking
- Modular and extensible for institutional requirements

## Architectural Diagram

```
+-------------------+         +---------------------+
|  Trading Engine   | <-----> |   RiskManager       |
+-------------------+         +---------------------+
         |                              |
         v                              v
+-------------------+         +---------------------+
| PositionTracker   | <-----> | Portfolio VaR (opt) |
+-------------------+         +---------------------+
         |
         v
+-------------------+
| Persistent State  |
+-------------------+
```

- **Trading Engine**: Submits orders, receives risk feedback.
- **RiskManager**: Validates orders, enforces risk rules, triggers liquidations.
- **PositionTracker**: Tracks and persists positions, open orders, and PnL.
- **Portfolio VaR**: (Optional) Advanced risk analytics.
- **Persistent State**: JSON file for recovery after restarts.

## Usage

- Instantiate `RiskManager` and `PositionTracker` in your trading engine.
- Call `risk_manager.validate_order(order)` before sending any order.
- Call `risk_manager.check_and_liquidate_on_loss()` after PnL updates.
- Update positions and open orders in `PositionTracker` as trades are filled or orders are placed/cancelled.

---

For more details, see the code in each file.
