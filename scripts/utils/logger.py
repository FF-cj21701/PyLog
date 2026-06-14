import logging
import os
import sys
from datetime import datetime

def setup_logger(name="PyLog", log_file="pylog.log", level=logging.INFO):
    """
    Sets up a professional logger that outputs to both console and a file.
    """
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    log_path = os.path.join(log_dir, log_file)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    # Create formatters
    # Standard industrial format: Timestamp - Name - Level - Message
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')

    # File handler
    try:
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(file_formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: Could not create log file: {e}")

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    return logger

# Create a default instances
logger = setup_logger()
memory_logger = logging.getLogger("PyLog.Memory") # For specific subsystem if needed
