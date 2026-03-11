"""Generic async retry/backoff engine."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable

from .errors import Action, ClassifiedError, StopError, ReauthError, NewChallengeError, BotcoinError

logger = logging.getLogger(__name__)

BACKOFF_STEPS = [2, 4, 8, 16, 30, 60]
JITTER_FRACTION = 0.25


async def with_retry(
    fn: Callable[..., Awaitable[Any]],
    classify_error: Callable[[Exception], ClassifiedError],
    max_attempts: int = 6,
    backoff: list[float] | None = None,
    jitter: float = JITTER_FRACTION,
) -> Any:
    backoff = backoff or BACKOFF_STEPS

    for attempt in range(max_attempts):
        try:
            return await fn()
        except (StopError, ReauthError, NewChallengeError):
            raise
        except Exception as exc:
            classified = classify_error(exc)
            step = backoff[min(attempt, len(backoff) - 1)]

            if classified.action == Action.STOP:
                raise StopError(classified) from exc
            if classified.action == Action.REAUTH:
                raise ReauthError(classified) from exc
            if classified.action == Action.NEW_CHALLENGE:
                raise NewChallengeError(classified) from exc
            if classified.action == Action.FIX_INPUT:
                raise StopError(classified) from exc

            delay = max(classified.retry_after or 0, step)
            delay += random.uniform(0, delay * jitter)

            if attempt < max_attempts - 1:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_attempts} failed: {classified.message}. "
                    f"Retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_attempts} attempts exhausted: {classified.message}")
                raise StopError(classified) from exc
