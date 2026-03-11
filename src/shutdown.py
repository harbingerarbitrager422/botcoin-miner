"""SIGINT/SIGTERM graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

logger = logging.getLogger(__name__)

_force_count = 0


def setup_shutdown(shutdown_event: asyncio.Event) -> None:
    def _handler(sig: int, frame) -> None:
        global _force_count
        _force_count += 1
        if _force_count >= 2:
            logger.warning("Force exit")
            sys.exit(1)
        logger.info("Shutting down gracefully (press Ctrl+C again to force)...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
