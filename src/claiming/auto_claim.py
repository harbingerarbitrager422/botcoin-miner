"""Background auto-claim triggered on epoch transitions during mining."""

from __future__ import annotations

import asyncio
import logging

from ..clients.coordinator import CoordinatorClient, CoordinatorAPIError
from ..clients.bankr import BankrClient
from .claim_log import log_claim_attempt
from .reward_decoder import get_claim_reward

logger = logging.getLogger(__name__)

# Retry schedule: wait this long before re-attempting a failed claim.
# Epochs may not be funded immediately after ending.
RETRY_DELAYS = [60, 300, 600]  # 1min, 5min, 10min


async def auto_claim_epoch(
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    epoch_id: int,
    pool: str | None = None,
    miner: str | None = None,
) -> None:
    """Claim regular + bonus rewards for a single epoch, with retries."""
    epoch_str = str(epoch_id)
    logger.info(f"Auto-claim: starting for epoch {epoch_str}")

    # --- Bonus claim ---
    await _try_bonus_claim(coordinator, bankr, epoch_id, epoch_str, pool, miner)

    # --- Regular claim with retries (epoch may not be funded yet) ---
    for attempt, delay in enumerate(RETRY_DELAYS, 1):
        success = await _try_regular_claim(coordinator, bankr, epoch_id, epoch_str, pool, miner)
        if success:
            return
        logger.info(f"Auto-claim: epoch {epoch_str} attempt {attempt}/{len(RETRY_DELAYS)} "
                     f"failed, retrying in {delay}s")
        await asyncio.sleep(delay)

    # Final attempt
    await _try_regular_claim(coordinator, bankr, epoch_id, epoch_str, pool, miner)


async def _try_bonus_claim(
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    epoch_id: int,
    epoch_str: str,
    pool: str | None,
    miner: str | None = None,
) -> bool:
    try:
        status = await coordinator.get_bonus_status(epoch_str)
        if not status.enabled or not status.isBonusEpoch:
            logger.info(f"Auto-claim: epoch {epoch_str} is not a bonus epoch")
            return False

        if not status.claimsOpen:
            logger.info(f"Auto-claim: bonus claims not open yet for epoch {epoch_str}")
            log_claim_attempt(epoch_id, "bonus", False, error="claims_not_open",
                              reward=status.reward)
            return False

        logger.info(f"Auto-claim: bonus epoch {epoch_str}! reward={status.reward} BOTCOIN")
        data = await coordinator.get_bonus_claim_calldata(epoch_str, target=pool)
        result = await bankr.submit_transaction(
            data.transaction, f"Bonus claim epoch {epoch_str}"
        )
        if result.success:
            reward = await get_claim_reward(result.transactionHash, miner) if result.transactionHash else None
            reward_str = f"{reward:,.2f}" if reward else status.reward
            logger.info(f"Auto-claim: bonus claimed tx={result.transactionHash} reward={reward_str}")
            log_claim_attempt(epoch_id, "bonus", True, tx_hash=result.transactionHash,
                              reward=reward_str)
            return True
        else:
            logger.warning(f"Auto-claim: bonus tx failed: {result}")
            log_claim_attempt(epoch_id, "bonus", False, error=f"tx_failed: {result.status}")
            return False
    except CoordinatorAPIError as e:
        logger.warning(f"Auto-claim: bonus check failed for epoch {epoch_str}: {e}")
        log_claim_attempt(epoch_id, "bonus", False, error=str(e))
        return False
    except Exception as e:
        logger.warning(f"Auto-claim: bonus unexpected error for epoch {epoch_str}: {e}")
        log_claim_attempt(epoch_id, "bonus", False, error=str(e))
        return False


async def _try_regular_claim(
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    epoch_id: int,
    epoch_str: str,
    pool: str | None,
    miner: str | None = None,
) -> bool:
    try:
        data = await coordinator.get_claim_calldata(epoch_str, target=pool)
        result = await bankr.submit_transaction(
            data.transaction, f"Claim epoch {epoch_str}"
        )
        if result.success:
            reward = await get_claim_reward(result.transactionHash, miner) if result.transactionHash else None
            reward_str = f"{reward:,.2f}" if reward else None
            logger.info(f"Auto-claim: epoch {epoch_str} claimed tx={result.transactionHash} reward={reward_str}")
            log_claim_attempt(epoch_id, "regular", True, tx_hash=result.transactionHash,
                              reward=reward_str)
            return True
        else:
            logger.warning(f"Auto-claim: epoch {epoch_str} tx failed: {result}")
            log_claim_attempt(epoch_id, "regular", False, error=f"tx_failed: {result.status}")
            return False
    except CoordinatorAPIError as e:
        error_msg = str(e)
        # AlreadyClaimed — nothing to do
        if "AlreadyClaimed" in error_msg:
            logger.info(f"Auto-claim: epoch {epoch_str} already claimed")
            log_claim_attempt(epoch_id, "regular", True, error="already_claimed")
            return True
        # NoCredits — we didn't actually mine in this epoch
        if "NoCredits" in error_msg:
            logger.info(f"Auto-claim: no credits in epoch {epoch_str}")
            log_claim_attempt(epoch_id, "regular", False, error="no_credits")
            return True  # not retryable
        # EpochNotFunded — operator hasn't funded yet, retry later
        if "EpochNotFunded" in error_msg or "not funded" in error_msg.lower():
            logger.info(f"Auto-claim: epoch {epoch_str} not funded yet")
            log_claim_attempt(epoch_id, "regular", False, error="not_funded")
            return False  # will retry
        logger.warning(f"Auto-claim: epoch {epoch_str} coordinator error: {e}")
        log_claim_attempt(epoch_id, "regular", False, error=error_msg)
        return False
    except Exception as e:
        logger.warning(f"Auto-claim: epoch {epoch_str} unexpected error: {e}")
        log_claim_attempt(epoch_id, "regular", False, error=str(e))
        return False
