# -*- coding: utf-8 -*-

import logging
import sys


def get_logger(filename: str = "", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("aggregator")
    if logger.handlers:
        return logger

    logger.setLevel(level=level)
    format = logging.Formatter("%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s: %(message)s")

    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setFormatter(format)
    stream_handler.setLevel(level=level)
    logger.addHandler(stream_handler)

    if filename:
        file_handler = logging.FileHandler(filename=filename, encoding="utf-8", mode="a")
        file_handler.setFormatter(format)
        file_handler.setLevel(level=level)
        logger.addHandler(file_handler)

    return logger


logger = get_logger()
