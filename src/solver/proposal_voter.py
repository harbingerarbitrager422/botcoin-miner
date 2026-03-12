"""LLM-based proposal voting — replaces hardcoded 'yes' vote."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from ..clients.llm import LLMClient

logger = logging.getLogger(__name__)


class ProposalVote(BaseModel):
    vote: str  # "yes" or "no"
    reasoning: str


VOTE_SYSTEM = """\
You are a governance voter for the BOTCOIN mining network. You will be given a proposal \
and must decide whether to vote YES or NO.

Evaluate the proposal based on:
1. Does it benefit the mining community and network health?
2. Is it technically sound and clearly specified?
3. Are there risks, hidden costs, or centralisation concerns?
4. Does it align with fair, decentralised operation?

Respond with your vote ("yes" or "no") and a brief reasoning (1-2 sentences)."""


async def evaluate_proposal(
    llm: LLMClient,
    proposal_text: str,
    model: str | None = None,
) -> tuple[str, str]:
    """Evaluate a proposal and return (vote, reasoning).

    Falls back to 'yes' if LLM fails.
    """
    result = await llm.generate_chat(
        system_prompt=VOTE_SYSTEM,
        user_prompt=f"PROPOSAL:\n{proposal_text}",
        response_model=ProposalVote,
        model=model or llm.small_model,
        temperature=0.0,
        max_tokens=256,
        max_retries=2,
    )

    if result:
        vote = result.get("vote", "").strip().lower()
        reasoning = result.get("reasoning", "").strip()
        if vote in ("yes", "no") and reasoning:
            logger.info(f"Proposal vote: {vote} — {reasoning}")
            return vote, reasoning
        logger.warning(f"Unexpected vote response: {result}, defaulting to yes")

    logger.warning("Proposal vote LLM failed, defaulting to yes")
    return "yes", "Supporting the proposal for community benefit."
