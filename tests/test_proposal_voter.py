"""Tests for solver/proposal_voter.py — LLM-based proposal voting."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.solver.proposal_voter import evaluate_proposal, ProposalVote, VOTE_SYSTEM


# -- Helpers -------------------------------------------------------------------


MOCK_SMALL_MODEL = "mock/small-model"


def _make_llm(response=None):
    """Create a mock LLMClient with configurable generate_chat response."""
    llm = MagicMock()
    llm.small_model = MOCK_SMALL_MODEL
    llm.generate_chat = AsyncMock(return_value=response)
    return llm


# -- Tests ---------------------------------------------------------------------


class TestEvaluateProposal:
    @pytest.mark.asyncio
    async def test_yes_vote(self):
        llm = _make_llm({"vote": "yes", "reasoning": "Good for the community."})
        vote, reasoning = await evaluate_proposal(llm, "Increase mining rewards by 10%")
        assert vote == "yes"
        assert reasoning == "Good for the community."

    @pytest.mark.asyncio
    async def test_no_vote(self):
        llm = _make_llm({"vote": "no", "reasoning": "This centralizes power."})
        vote, reasoning = await evaluate_proposal(llm, "Give admin all tokens")
        assert vote == "no"
        assert reasoning == "This centralizes power."

    @pytest.mark.asyncio
    async def test_vote_case_insensitive(self):
        llm = _make_llm({"vote": "YES", "reasoning": "Looks good."})
        vote, reasoning = await evaluate_proposal(llm, "Some proposal")
        assert vote == "yes"

    @pytest.mark.asyncio
    async def test_vote_with_whitespace(self):
        llm = _make_llm({"vote": " yes ", "reasoning": " Great idea. "})
        vote, reasoning = await evaluate_proposal(llm, "Some proposal")
        assert vote == "yes"
        assert reasoning == "Great idea."

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        """If LLM returns None, defaults to yes."""
        llm = _make_llm(None)
        vote, reasoning = await evaluate_proposal(llm, "Some proposal")
        assert vote == "yes"
        assert "community benefit" in reasoning.lower()

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_vote(self):
        """If LLM returns unexpected vote value, defaults to yes."""
        llm = _make_llm({"vote": "maybe", "reasoning": "Not sure."})
        vote, reasoning = await evaluate_proposal(llm, "Some proposal")
        assert vote == "yes"
        assert "community benefit" in reasoning.lower()

    @pytest.mark.asyncio
    async def test_fallback_on_empty_reasoning(self):
        """If LLM returns empty reasoning, defaults to yes."""
        llm = _make_llm({"vote": "no", "reasoning": ""})
        vote, reasoning = await evaluate_proposal(llm, "Some proposal")
        assert vote == "yes"
        assert "community benefit" in reasoning.lower()

    @pytest.mark.asyncio
    async def test_fallback_on_missing_keys(self):
        """If LLM returns dict without expected keys, defaults to yes."""
        llm = _make_llm({"answer": "yes"})
        vote, reasoning = await evaluate_proposal(llm, "Some proposal")
        assert vote == "yes"

    @pytest.mark.asyncio
    async def test_uses_small_model_by_default(self):
        llm = _make_llm({"vote": "yes", "reasoning": "Good."})
        await evaluate_proposal(llm, "Some proposal")
        call_kwargs = llm.generate_chat.call_args
        assert call_kwargs.kwargs["model"] == MOCK_SMALL_MODEL

    @pytest.mark.asyncio
    async def test_model_override(self):
        llm = _make_llm({"vote": "yes", "reasoning": "Good."})
        await evaluate_proposal(llm, "Some proposal", model="custom/model")
        call_kwargs = llm.generate_chat.call_args
        assert call_kwargs.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_passes_proposal_text(self):
        llm = _make_llm({"vote": "yes", "reasoning": "Good."})
        await evaluate_proposal(llm, "Increase block rewards to 500 BOTCOIN")
        call_args = llm.generate_chat.call_args
        assert "Increase block rewards to 500 BOTCOIN" in call_args.kwargs["user_prompt"]

    @pytest.mark.asyncio
    async def test_system_prompt_content(self):
        llm = _make_llm({"vote": "yes", "reasoning": "Good."})
        await evaluate_proposal(llm, "Some proposal")
        call_args = llm.generate_chat.call_args
        assert call_args.kwargs["system_prompt"] == VOTE_SYSTEM

    @pytest.mark.asyncio
    async def test_uses_proposal_vote_schema(self):
        llm = _make_llm({"vote": "yes", "reasoning": "Good."})
        await evaluate_proposal(llm, "Some proposal")
        call_args = llm.generate_chat.call_args
        assert call_args.kwargs["response_model"] is ProposalVote


class TestProposalVoteModel:
    def test_valid(self):
        v = ProposalVote(vote="yes", reasoning="Good proposal.")
        assert v.vote == "yes"
        assert v.reasoning == "Good proposal."

    def test_no_vote(self):
        v = ProposalVote(vote="no", reasoning="Bad idea.")
        assert v.vote == "no"
