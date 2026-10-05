"""Tempo por etapa no log (`tempo <etapa>: N ms`), para achar onde a lentidão está."""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("app.timing")


@contextmanager
def timed(step: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info("tempo %s: %d ms", step, (time.perf_counter() - start) * 1000)
