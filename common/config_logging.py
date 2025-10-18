import logging
import sys

# Configure logging to console
def to_stdout():
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Clear existing handlers
    root.handlers = []

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    log_formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s] [%(name)s] %(message)s")
    handler.setFormatter(log_formatter)
    root.addHandler(handler)


# Get a logger that writes to given file
def get_file_logger(name: str, log_file: str):
    handler = logging.FileHandler(log_file)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger
