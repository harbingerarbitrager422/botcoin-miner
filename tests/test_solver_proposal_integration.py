"""Integration test: verify proposal vote is wired into solve_challenge correctly."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.types import Challenge
from src.solver.extractor import CompanyData


def _make_company():
    return CompanyData(
        name="TestCo", hq_city="NYC", hq_country="US", sector="Tech",
        ceo_full_name="John Doe", employees=100, is_public=True,
        founding_year=2000, q1_revenue_m=500, q1_growth_pct=5,
        q2_revenue_m=510, q2_growth_pct=6, q3_revenue_m=520,
        q3_growth_pct=7, q4_revenue_m=530, q4_growth_pct=8,
        debt_to_equity=0.5, satisfaction_rating=4.0,
    )


def _make_challenge(proposal=None):
    """Minimal challenge for testing proposal integration."""
    return Challenge(
        epochId=20,
        doc="TestCo has 100 employees and $500M revenue in Q1. " * 50,
        questions=["Which company has the most employees?"],
        constraints=["The artifact must be exactly 50 words."],
        companies=["TestCo"],
        challengeId="test123",
        creditsPerSolve=1,
        proposal=proposal,
    )


class TestSolverProposalWiring:
    @pytest.mark.asyncio
    async def test_proposal_vote_appended_to_candidates(self):
        """When challenge has a proposal, vote suffix is appended to all candidates."""
        mock_company = _make_company()

        with patch(
            "src.solver.solver.evaluate_proposal",
            new_callable=AsyncMock,
            return_value=("no", "This harms miners."),
        ) as mock_vote, patch(
            "src.solver.solver.extract_all_companies",
            new_callable=AsyncMock,
            return_value=[mock_company],
        ), patch(
            "src.solver.solver._answer_from_doc",
            new_callable=AsyncMock,
            return_value="TestCo",
        ), patch(
            "src.solver.solver._answer_from_table",
            new_callable=AsyncMock,
            return_value="TestCo",
        ), patch(
            "src.solver.solver._parse_constraints_llm",
            new_callable=AsyncMock,
        ) as mock_parse, patch(
            "src.solver.solver._build_artifact_llm",
            new_callable=AsyncMock,
            return_value="test artifact words " * 5,
        ):
            from src.solver.models import ConstraintParseResponse
            mock_parse.return_value = ConstraintParseResponse(
                word_count=50, acrostic="", forbidden_letter="",
                required_inclusions=[], prime_value=None, equation="",
            )

            from src.solver.solver import solve_challenge

            llm = MagicMock()
            llm.large_model = "test-model"
            llm.generate_chat = AsyncMock(return_value=None)

            challenge = _make_challenge(proposal="Give all tokens to admin")
            result = await solve_challenge(llm, challenge, model="test-small", large_model="test-large")

            # evaluate_proposal was called
            mock_vote.assert_called_once()
            call_args = mock_vote.call_args
            assert call_args.args[1] == "Give all tokens to admin"

            # Result should contain the vote suffix
            assert result is not None
            candidates, _ = result
            assert len(candidates) > 0
            assert "VOTE: no" in candidates[0][0]
            assert "This harms miners." in candidates[0][0]

    @pytest.mark.asyncio
    async def test_no_proposal_no_vote_call(self):
        """When challenge has no proposal, evaluate_proposal is never called."""
        mock_company = _make_company()

        with patch(
            "src.solver.solver.evaluate_proposal",
            new_callable=AsyncMock,
        ) as mock_vote, patch(
            "src.solver.solver.extract_all_companies",
            new_callable=AsyncMock,
            return_value=[mock_company],
        ), patch(
            "src.solver.solver._answer_from_doc",
            new_callable=AsyncMock,
            return_value="TestCo",
        ), patch(
            "src.solver.solver._answer_from_table",
            new_callable=AsyncMock,
            return_value="TestCo",
        ), patch(
            "src.solver.solver._parse_constraints_llm",
            new_callable=AsyncMock,
        ) as mock_parse, patch(
            "src.solver.solver._build_artifact_llm",
            new_callable=AsyncMock,
            return_value="test artifact words " * 5,
        ):
            from src.solver.models import ConstraintParseResponse
            mock_parse.return_value = ConstraintParseResponse(
                word_count=50, acrostic="", forbidden_letter="",
                required_inclusions=[], prime_value=None, equation="",
            )

            from src.solver.solver import solve_challenge

            llm = MagicMock()
            llm.large_model = "test-model"
            llm.generate_chat = AsyncMock(return_value=None)

            challenge = _make_challenge(proposal=None)
            result = await solve_challenge(llm, challenge, model="test-small", large_model="test-large")

            mock_vote.assert_not_called()
