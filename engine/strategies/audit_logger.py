"""
Per-Strategy Audit Logger

Provides CSV-based audit logging for trading strategies with daily rotation.
Logs detailed information about strategy decisions, indicators, and position states.
"""

import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from nautilus_trader.model.data import Bar


class StrategyAuditLogger:
    """
    Per-strategy CSV audit logger with daily rotation.

    Creates separate CSV files for each strategy and symbol, with automatic
    daily rotation. Logs detailed information about strategy decisions,
    indicators, position states, and trading conditions.
    """

    def __init__(self, strategy_name: str, symbol: str, audit_dir: str = "audit_logs"):
        """
        Initialize the audit logger.

        Args:
            strategy_name: Name of the strategy (e.g., "ROCMeanReversionStrategy")
            symbol: Trading symbol (e.g., "ETHUSDT")
            audit_dir: Directory to store audit log files
        """
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(exist_ok=True)

        self.current_date = None
        self.csv_file = None
        self.csv_writer = None
        self.header_written = False

    def log(
        self,
        bar: Bar,
        action: str = "",
        indicators: Optional[Dict[str, Any]] = None,
        position_state: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log audit entry with automatic daily rotation.

        Args:
            bar: Current bar data
            action: Action taken (e.g., "ENTRY_LONG", "EXIT_SHORT", "")
            indicators: Dictionary of indicator values
            position_state: Dictionary of position state information
            conditions: Dictionary of condition check results
        """
        try:
            # Check if we need to rotate the file (new day)
            self._rotate_file_if_needed()

            if not self.csv_writer:
                return

            # Prepare data for CSV row
            timestamp = datetime.fromtimestamp(bar.ts_init / 1_000_000_000, tz=timezone.utc)

            # Default values
            indicators = indicators or {}
            position_state = position_state or {}
            conditions = conditions or {}

            # Create CSV row
            row = {
                "timestamp": timestamp.isoformat(),
                "bar_open": float(bar.open),
                "bar_high": float(bar.high),
                "bar_low": float(bar.low),
                "bar_close": float(bar.close),
                "bar_volume": float(bar.volume),
                "action_taken": action,
                "position_state": position_state.get("state", "flat"),
                "bars_held": position_state.get("bars_held", 0),
                "entry_price": position_state.get("entry_price", 0.0),
                "stop_loss_price": position_state.get("stop_loss_price", 0.0),
                "exit_price": position_state.get("exit_price", 0.0),
            }

            # Add all indicator values
            for key, value in indicators.items():
                row[f"indicator_{key}"] = value

            # Add all condition checks
            for key, value in conditions.items():
                row[f"condition_{key}"] = value

            # Write row to CSV
            if self.csv_writer:
                # If this is the first row, write header first with all fieldnames
                if not self.header_written:
                    self.csv_writer.writerow(list(row.keys()))
                    self.header_written = True

                # Write data row
                self.csv_writer.writerow(list(row.values()))
                self.csv_file.flush()

        except Exception as e:
            print(f"Error writing audit log: {e}")

    def _rotate_file_if_needed(self) -> None:
        """Create new CSV file if date changed."""
        current_date = datetime.now(timezone.utc).date()

        # If no file is open or date has changed, create new file
        if self.csv_file is None or self.current_date != current_date:
            # Close current file if open
            if self.csv_file:
                self.csv_file.close()

            # Create new file for today
            date_str = current_date.strftime("%Y%m%d")
            filename = f"{self.strategy_name}_{self.symbol}_{date_str}.csv"
            file_path = self.audit_dir / filename

            self.csv_file = open(file_path, "w", newline="", encoding="utf-8")
            self.current_date = current_date
            self.header_written = False

            # Write header for new file
            self._write_header()

    def _write_header(self) -> None:
        """Write CSV header row."""
        if not self.csv_file:
            return

        # Create CSV writer
        self.csv_writer = csv.writer(self.csv_file)

        # Don't write header yet - we'll write it with the first data row
        self.header_written = False

    def close(self) -> None:
        """Close current CSV file."""
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
