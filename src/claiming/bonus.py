"""Bonus epoch detection + claim."""

from __future__ import annotations

import logging

from ..clients.coordinator import CoordinatorClient
from ..clients.bankr import BankrClient
from .claim_log import log_claim_attempt

logger = logging.getLogger(__name__)


async def check_and_claim_bonus(
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    epochs: str,
    pool: str | None = None,
) -> None:
    logger.info(f"Checking bonus status for epochs: {epochs}")

    status = await coordinator.get_bonus_status(epochs)
    if not status.enabled:
        logger.info("Bonus not enabled")
        return

    if not status.isBonusEpoch:
        logger.info(f"Epoch {status.epochId} is not a bonus epoch")
        return

    if not status.claimsOpen:
        logger.info(f"Bonus claims not open yet for epoch {status.epochId}")
        log_claim_attempt(status.epochId or epochs, "bonus", False,
                          error="claims_not_open", reward=status.reward)
        return

    logger.info(f"Bonus epoch {status.epochId}! Reward: {status.reward} BOTCOIN. Claiming...")
    data = await coordinator.get_bonus_claim_calldata(epochs, target=pool)
    result = await bankr.submit_transaction(
        data.transaction, f"Claim BOTCOIN bonus rewards (epochs {epochs})"
    )
    if result.success:
        logger.info(f"Bonus claimed: tx={result.transactionHash}")
        log_claim_attempt(status.epochId or epochs, "bonus", True,
                          tx_hash=result.transactionHash, reward=status.reward)
    else:
        logger.error(f"Bonus claim failed: {result}")
        log_claim_attempt(status.epochId or epochs, "bonus", False,
                          error=f"tx_failed: {result.status}")
