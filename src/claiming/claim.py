"""Regular + legacy epoch claims."""

from __future__ import annotations

import logging

from ..clients.coordinator import CoordinatorClient
from ..clients.bankr import BankrClient
from .claim_log import log_claim_attempt
from .reward_decoder import get_claim_reward

logger = logging.getLogger(__name__)


async def claim_epochs(
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    epochs: str,
    pool: str | None = None,
    legacy: bool = False,
    miner: str | None = None,
) -> None:
    claim_type = "legacy" if legacy else "regular"
    logger.info(f"Claiming epochs: {epochs} (pool={pool or 'none'}, legacy={legacy})")

    if legacy:
        data = await coordinator.get_legacy_claim_calldata(epochs)
    else:
        data = await coordinator.get_claim_calldata(epochs, target=pool)

    result = await bankr.submit_transaction(data.transaction, f"Claim BOTCOIN rewards (epochs {epochs})")
    if result.success:
        reward = await get_claim_reward(result.transactionHash, miner) if result.transactionHash else None
        reward_str = f"{reward:,.2f}" if reward else None
        logger.info(f"Claimed: tx={result.transactionHash} reward={reward_str} BOTCOIN")
        for eid in epochs.split(","):
            log_claim_attempt(eid.strip(), claim_type, True, tx_hash=result.transactionHash,
                              reward=reward_str)
    else:
        logger.error(f"Claim failed: {result}")
        for eid in epochs.split(","):
            log_claim_attempt(eid.strip(), claim_type, False, error=f"tx_failed: {result.status}")
