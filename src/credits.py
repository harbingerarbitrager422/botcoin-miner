"""LLM credit management via Bankr gateway and agent prompt."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def get_usage(llm_client, days: int = 1) -> dict:
    """Get recent LLM usage data."""
    return await llm_client.get_usage(days=days)


async def setup_auto_topup(
    bankr,
    amount: int = 25,
    threshold: int = 5,
    token: str = "USDC",
) -> bool:
    """Configure auto top-up via Bankr agent prompt endpoint."""
    prompt = (
        f"bankr llm credits auto --enable "
        f"--amount {amount} --threshold {threshold} --tokens {token}"
    )
    try:
        resp = await bankr.client.post(
            "https://api.bankr.bot/agent/prompt",
            json={"prompt": prompt},
        )
        if resp.status_code not in (200, 202):
            logger.error(f"Auto top-up setup failed: {resp.status_code} {resp.text[:200]}")
            return False

        data = resp.json()
        job_id = data.get("jobId")
        if not job_id:
            logger.info("Auto top-up configured (no job to poll)")
            return True

        # Poll for completion
        for _ in range(30):
            await asyncio.sleep(2)
            poll = await bankr.client.get(
                f"https://api.bankr.bot/agent/job/{job_id}",
            )
            if poll.status_code in (200, 202):
                result = poll.json()
                status = result.get("status", "")
                if status in ("completed", "success", "done"):
                    logger.info("Auto top-up configured successfully")
                    return True
                if status in ("failed", "error"):
                    logger.error(f"Auto top-up failed: {result}")
                    return False
                # Still pending — keep polling

        logger.warning("Auto top-up setup timed out")
        return False
    except Exception as e:
        logger.error(f"Auto top-up setup error: {e}")
        return False


async def add_credits(bankr, amount: int = 25) -> bool:
    """Add LLM credits via Bankr agent prompt endpoint."""
    prompt = f"bankr llm credits add {amount}"
    try:
        resp = await bankr.client.post(
            "https://api.bankr.bot/agent/prompt",
            json={"prompt": prompt},
        )
        if resp.status_code not in (200, 202):
            logger.error(f"Add credits failed: {resp.status_code} {resp.text[:200]}")
            return False

        data = resp.json()
        job_id = data.get("jobId")
        if not job_id:
            logger.info(f"Credits added: ${amount}")
            return True

        for _ in range(30):
            await asyncio.sleep(2)
            poll = await bankr.client.get(
                f"https://api.bankr.bot/agent/job/{job_id}",
            )
            if poll.status_code in (200, 202):
                result = poll.json()
                status = result.get("status", "")
                if status in ("completed", "success", "done"):
                    logger.info(f"Credits added: ${amount}")
                    return True
                if status in ("failed", "error"):
                    logger.error(f"Add credits failed: {result}")
                    return False
                # Still pending — keep polling

        logger.warning("Add credits timed out")
        return False
    except Exception as e:
        logger.error(f"Add credits error: {e}")
        return False
