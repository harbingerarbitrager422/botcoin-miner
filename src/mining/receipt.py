"""Post receipt on-chain via Bankr."""

from __future__ import annotations

import logging

from ..clients.bankr import BankrClient, BankrAPIError
from ..errors import classify_bankr_error, Action, ClassifiedError
from ..retry import with_retry
from ..types import OnChainTransaction, BankrSubmitResponse

logger = logging.getLogger(__name__)


async def post_receipt(bankr: BankrClient, tx: OnChainTransaction) -> BankrSubmitResponse:
    def classify(exc: Exception) -> ClassifiedError:
        if isinstance(exc, BankrAPIError):
            return exc.classified
        return ClassifiedError(Action.RETRY, str(exc))

    result = await with_retry(
        lambda: bankr.submit_transaction(tx, "Post BOTCOIN mining receipt"),
        classify,
        max_attempts=3,
        backoff=[5, 15, 30],
    )
    return result
