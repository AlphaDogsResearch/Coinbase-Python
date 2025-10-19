"""
Risk configuration for reporting and limits.
"""
from typing import List, Optional

# Reporting
REPORTING_PERIOD = 600
RISK_REPORT_ENABLED_DEFAULT: bool = True
RISK_REPORT_FILE_DEFAULT: str = "logs/risk_report.log"
RISK_REPORT_INTERVAL_SECONDS_DEFAULT: int = REPORTING_PERIOD

# Optional list of symbols to include; if None, include all registered symbols
RISK_REPORT_SYMBOLS_DEFAULT: Optional[List[str]] = None

# Limits (can be overridden via environment variables if desired)
MAX_ORDER_VALUE_DEFAULT: float = 5000.0
MAX_POSITION_VALUE_DEFAULT: float = 20000.0
MAX_LEVERAGE_DEFAULT: float = 5.0
MAX_OPEN_ORDERS_DEFAULT: int = 20
MAX_LOSS_PER_DAY_DEFAULT: float = 0.15
MAX_VAR_RATIO_DEFAULT: float = 0.15
MIN_ORDER_SIZE_DEFAULT: float = 0.001
LIQUIDATION_LOSS_THRESHOLD_DEFAULT: float = 0.25

# Optional whitelist; if None, allow all symbols
ALLOWED_SYMBOLS_DEFAULT: Optional[List[str]] = None
