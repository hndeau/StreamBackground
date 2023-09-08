import logging
from datetime import datetime
import sys


def setup_logging():
    # Determine the logging level based on command-line arguments
    if "--debug-error" in sys.argv:
        logging_level = logging.ERROR
    elif "--debug-warning" in sys.argv:
        logging_level = logging.WARNING
    else:
        logging_level = logging.INFO  # Default to INFO if no flags are provided

    # Create a logger object
    logger = logging.getLogger(__name__)
    logger.setLevel(logging_level)  # Set the logging level for the logger object

    # Setup logging to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging_level)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Setup logging to a file
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{current_time}.log"
    file_handler = logging.FileHandler(filename)
    file_handler.setLevel(logging_level)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger



# Global Logging Var
logger = setup_logging()
