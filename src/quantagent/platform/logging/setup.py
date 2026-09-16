"""结构化日志。格式统一带 ``run_id``，没有绑定则为 ``-``。"""

from __future__ import annotations

import logging
import sys

from quantagent.platform.logging.context import run_id_var

_LOGGER_NAME = "quantagent"


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


def configure_logging(*, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s run_id=%(run_id)s %(name)s %(message)s")
        )
        handler.addFilter(RunIdFilter())
        logger.addHandler(handler)
    elif not any(isinstance(f, RunIdFilter) for h in logger.handlers for f in h.filters):
        logger.handlers[0].addFilter(RunIdFilter())
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if name is None or name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    if name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
