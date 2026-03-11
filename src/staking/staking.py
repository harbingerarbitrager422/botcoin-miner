"""Approve + stake, unstake, withdraw."""

from __future__ import annotations

import logging

from ..clients.coordinator import CoordinatorClient
from ..clients.bankr import BankrClient

logger = logging.getLogger(__name__)

DECIMALS = 18


def _to_wei(whole_tokens: int) -> str:
    return str(whole_tokens * (10 ** DECIMALS))


async def stake(coordinator: CoordinatorClient, bankr: BankrClient, amount: int) -> None:
    wei = _to_wei(amount)
    logger.info(f"Staking {amount:,} BOTCOIN ({wei} wei)...")

    # Step 1: Approve
    logger.info("Getting approve calldata...")
    approve = await coordinator.get_stake_approve_calldata(wei)
    logger.info("Submitting approve transaction...")
    result = await bankr.submit_transaction(approve.transaction, "Approve BOTCOIN for staking")
    if not result.success:
        logger.error(f"Approve failed: {result}")
        return
    logger.info(f"Approved: tx={result.transactionHash}")

    # Step 2: Stake
    logger.info("Getting stake calldata...")
    stake_data = await coordinator.get_stake_calldata(wei)
    logger.info("Submitting stake transaction...")
    result = await bankr.submit_transaction(stake_data.transaction, "Stake BOTCOIN")
    if not result.success:
        logger.error(f"Stake failed: {result}")
        return
    logger.info(f"Staked {amount:,} BOTCOIN: tx={result.transactionHash}")


async def unstake(coordinator: CoordinatorClient, bankr: BankrClient) -> None:
    logger.info("Requesting unstake (24h cooldown starts)...")
    data = await coordinator.get_unstake_calldata()
    result = await bankr.submit_transaction(data.transaction, "Request BOTCOIN unstake")
    if result.success:
        logger.info(f"Unstake requested: tx={result.transactionHash}")
    else:
        logger.error(f"Unstake failed: {result}")


async def withdraw(coordinator: CoordinatorClient, bankr: BankrClient) -> None:
    logger.info("Withdrawing staked BOTCOIN...")
    data = await coordinator.get_withdraw_calldata()
    result = await bankr.submit_transaction(data.transaction, "Withdraw staked BOTCOIN")
    if result.success:
        logger.info(f"Withdrawn: tx={result.transactionHash}")
    else:
        logger.error(f"Withdraw failed: {result}")
