import logging
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler


class UTCFormatter(logging.Formatter):
    """Custom formatter that uses UTC time in ISO 8601 format with 'Z' suffix."""

    converter = time.gmtime  # Use UTC time

    def formatTime(self, record, datefmt=None):
        """Format time as ISO 8601 with milliseconds and 'Z' suffix."""
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            # ISO 8601 format: 2025-10-30T16:42:15.123Z
            t = time.strftime("%Y-%m-%dT%H:%M:%S", ct)
            s = f"{t}.{int(record.msecs):03d}Z"
        return s


# Configure logging to console
def to_stdout():
    # Get log level from environment variable (default: INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = log_level_map.get(log_level_str, logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Clear existing handlers
    root.handlers = []

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    log_formatter = UTCFormatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(name)s] %(message)s"
    )
    handler.setFormatter(log_formatter)
    root.addHandler(handler)

    logging.info("Logging configured with level: %s (timestamps in ISO 8601 UTC)", log_level_str)


def to_stdout_and_file(log_dir: str = "logs", log_prefix: str = "trading"):
    """
    Configure logging to both console (stdout) and a timestamped log file.

    Args:
        log_dir: Directory to store log files (default: "logs")
        log_prefix: Prefix for log filename (default: "trading")

    Example:
        to_stdout_and_file()  # Logs to logs/trading_20251029_123456.log
    """
    # Get log level from environment variable (default: INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = log_level_map.get(log_level_str, logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Clear existing handlers
    root.handlers = []

    # Formatter for all handlers (ISO 8601 UTC timestamps)
    log_formatter = UTCFormatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(name)s] %(message)s"
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_formatter)
    root.addHandler(console_handler)

    # File handler (timestamped log file)
    try:
        # Create logs directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = log_path / f"{log_prefix}_{timestamp}.log"

        file_handler = logging.FileHandler(log_filename, mode="w", encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(log_formatter)
        root.addHandler(file_handler)

        logging.info(
            "Logging configured with level: %s (timestamps in ISO 8601 UTC)", log_level_str
        )
        logging.info("Log file: %s", log_filename)

    except Exception as e:
        logging.warning("Failed to create log file: %s (continuing with console only)", e)


def to_stdout_and_daily_file(log_dir: str = "logs", log_prefix: str = "trading"):
    """
    Configure logging to both console and a daily rotating log file (rotates at midnight UTC).

    Each day gets a new log file named: {log_prefix}_YYYYMMDD.log
    Old logs are automatically kept with date suffix.

    Args:
        log_dir: Directory to store log files (default: "logs")
        log_prefix: Prefix for log filename (default: "trading")

    Example:
        to_stdout_and_daily_file()
        # Creates: logs/trading_20251029.log (rotates at midnight UTC)
    """
    # Get log level from environment variable (default: INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = log_level_map.get(log_level_str, logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Clear existing handlers
    root.handlers = []

    # Formatter for all handlers (ISO 8601 UTC timestamps)
    log_formatter = UTCFormatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(name)s] %(message)s"
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_formatter)
    root.addHandler(console_handler)

    # Daily rotating file handler
    try:
        # Create logs directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # Get today's date in UTC
        today_utc = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_filename = log_path / f"{log_prefix}_{today_utc}.log"

        # Create rotating file handler
        # - Rotates at midnight UTC
        # - Keeps all backup files
        file_handler = TimedRotatingFileHandler(
            filename=str(log_filename),
            when="midnight",
            interval=1,
            backupCount=0,  # Keep all logs (no automatic deletion)
            encoding="utf-8",
            utc=True,  # Use UTC for rotation timing
        )

        # Set custom suffix for rotated files (YYYYMMDD format)
        file_handler.suffix = "%Y%m%d"

        file_handler.setLevel(log_level)
        file_handler.setFormatter(log_formatter)
        root.addHandler(file_handler)

        logging.info(
            "Logging configured with level: %s (timestamps in ISO 8601 UTC)", log_level_str
        )
        logging.info("Daily log file: %s (rotates at midnight UTC)", log_filename)
        logging.info(
            "Current UTC time: %s", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        )

    except Exception as e:
        logging.warning("Failed to create daily log file: %s (continuing with console only)", e)


# Get a logger that writes to given file
def get_file_logger(name: str, log_file: str):
    handler = logging.FileHandler(log_file)

    # Format with ISO 8601 UTC timestamps
    formatter = UTCFormatter("%(asctime)s [%(levelname)-5.5s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger
