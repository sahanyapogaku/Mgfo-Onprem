import logging
import os

from etl import config


def setup_logging():
    log_dir = os.path.dirname(config.ETL_LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    level = getattr(logging, config.ETL_LOG_LEVEL.upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    file_handler = logging.FileHandler(config.ETL_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(file_handler)
