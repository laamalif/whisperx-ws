import logging
import sys
import os

def init_logging():
    """
    Set up the root logger to print to stdout with a structured format.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )