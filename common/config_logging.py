import logging
import sys
import os


# Configure logging to console
def to_stdout():
    # Get log level from environment variable (default: DEBUG)
    log_level_str = os.getenv("LOG_LEVEL", "DEBUG").upper()
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
    log_formatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(name)s] %(message)s"
    )
    handler.setFormatter(log_formatter)
    root.addHandler(handler)

    logging.info("Logging configured with level: %s", log_level_str)


# Get a logger that writes to given file
def get_file_logger(name: str, log_file: str):
    handler = logging.FileHandler(log_file)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger
