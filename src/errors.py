"""Classified errors with action hints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    RETRY = "retry"
    STOP = "stop"
    REAUTH = "reauth"
    NEW_CHALLENGE = "new_challenge"
    WAIT_LONG = "wait_long"
    FIX_INPUT = "fix_input"
    INSUFFICIENT_CREDITS = "insufficient_credits"


@dataclass
class ClassifiedError:
    action: Action
    message: str
    retry_after: float | None = None


class BotcoinError(Exception):
    def __init__(self, classified: ClassifiedError):
        self.classified = classified
        super().__init__(classified.message)


class StopError(BotcoinError):
    """Unrecoverable — must stop."""


class ReauthError(BotcoinError):
    """Token expired — need fresh auth."""


class NewChallengeError(BotcoinError):
    """Current challenge is stale — fetch a new one."""


def classify_coordinator_error(endpoint: str, status: int, body: dict | str) -> ClassifiedError:
    msg = body if isinstance(body, str) else body.get("error", str(body))

    if status == 401:
        if endpoint in ("challenge", "submit"):
            return ClassifiedError(Action.REAUTH, f"401 on {endpoint}: {msg}")
        return ClassifiedError(Action.STOP, f"401 on {endpoint}: {msg}")

    if status == 403:
        return ClassifiedError(Action.STOP, f"403 on {endpoint}: {msg}")

    if status == 404:
        if endpoint == "submit":
            return ClassifiedError(Action.NEW_CHALLENGE, f"404 stale challenge: {msg}")
        return ClassifiedError(Action.STOP, f"404 on {endpoint}: {msg}")

    if status == 400:
        if endpoint in ("claim-calldata", "stake-approve-calldata", "stake-calldata", "bonus/claim-calldata"):
            return ClassifiedError(Action.FIX_INPUT, f"400 on {endpoint}: {msg}")
        return ClassifiedError(Action.STOP, f"400 on {endpoint}: {msg}")

    if status == 429 or status >= 500:
        retry_after = None
        if isinstance(body, dict):
            retry_after = body.get("retryAfterSeconds")
        return ClassifiedError(Action.RETRY, f"{status} on {endpoint}: {msg}", retry_after)

    return ClassifiedError(Action.STOP, f"Unexpected {status} on {endpoint}: {msg}")


def classify_bankr_error(status: int, body: dict | str) -> ClassifiedError:
    msg = body if isinstance(body, str) else body.get("error", str(body))

    if status == 401:
        return ClassifiedError(Action.STOP, f"Bankr 401: invalid API key. Check BANKR_API.")
    if status == 403:
        return ClassifiedError(Action.STOP, f"Bankr 403: no write access. Enable Agent API at bankr.bot/api.")
    if status == 429:
        return ClassifiedError(Action.RETRY, f"Bankr 429: rate limited", retry_after=60.0)
    if status >= 500:
        return ClassifiedError(Action.RETRY, f"Bankr {status}: {msg}", retry_after=5.0)

    return ClassifiedError(Action.STOP, f"Bankr {status}: {msg}")
