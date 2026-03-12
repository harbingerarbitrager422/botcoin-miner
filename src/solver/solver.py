"""Orchestrator: Extract → Answer → Constrain → Build (pure LLM pipeline).

Flow:
  1. Extract all 25 companies (per-company LLM calls, parallel)
     + Answer all questions from raw doc (parallel LLM calls)
     + Answer all questions from extracted data table (after extraction)
     → Merge: consensus or LLM tiebreaker
  2. Verify constraint-critical companies (focused re-extraction)
  3. Parse constraints via LLM → programmatic validation
  4. Build artifact via LLM → programmatic validation + retry
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..types import Challenge
from ..clients.llm import LLMClient
from .extractor import CompanyData, extract_all_companies, verify_critical_company
from .proposal_voter import evaluate_proposal
from .models import SingleQA, ConstraintParseResponse, ArtifactResponse
from .prompts import QA_SYSTEM, QA_TABLE_SYSTEM, CONSTRAINT_SYSTEM, ARTIFACT_SYSTEM
from .validator import (
    validate_constraint_parse,
    validate_artifact,
    validate_equation,
    is_prime,
    next_prime,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────

def _format_data_table(companies: list[CompanyData]) -> str:
    lines = []
    for c in companies:
        tr = c.q1_revenue_m + c.q2_revenue_m + c.q3_revenue_m + c.q4_revenue_m
        ag = (c.q1_growth_pct + c.q2_growth_pct + c.q3_growth_pct + c.q4_growth_pct) / 4
        lines.append(
            f"{c.name} | HQ: {c.hq_city}, {c.hq_country} | sector: {c.sector} | "
            f"CEO: {c.ceo_full_name} | emp: {c.employees} | "
            f"{'public' if c.is_public else 'private'} | founded: {c.founding_year} | "
            f"IPO: {c.ipo_year or 'N/A'} | "
            f"rev: Q1={c.q1_revenue_m} Q2={c.q2_revenue_m} Q3={c.q3_revenue_m} Q4={c.q4_revenue_m} total={tr} | "
            f"growth: Q1={c.q1_growth_pct} Q2={c.q2_growth_pct} Q3={c.q3_growth_pct} Q4={c.q4_growth_pct} avg={ag:.2f} | "
            f"D/E: {c.debt_to_equity} | sat: {c.satisfaction_rating}"
        )
    return "\n".join(lines)


def _match_company_name(name: str, valid_names: list[str]) -> str | None:
    if not name:
        return None
    if name in valid_names:
        return name
    name_lower = name.lower()
    for cn in valid_names:
        if cn.lower() == name_lower:
            return cn
    matches = [cn for cn in valid_names
               if cn.lower() in name_lower or name_lower in cn.lower()]
    if len(matches) == 1:
        return matches[0]
    return None


def _validate_artifact_simple(artifact: str, parsed: ConstraintParseResponse) -> list[str]:
    """Wrapper around validator for artifact checks."""
    return validate_artifact(artifact, parsed)


# ── Stage 1: Question Answering ──────────────────────────────────────────

async def _answer_from_doc(
    llm: LLMClient,
    doc: str,
    question: str,
    company_names: list[str],
    model: str | None,
) -> str | None:
    """Answer a question directly from the raw document using LLM."""
    result = await llm.generate_chat(
        system_prompt=QA_SYSTEM,
        user_prompt=(
            f"COMPANY NAMES: {', '.join(company_names)}\n\n"
            f"DOCUMENT:\n{doc}\n\n"
            f"QUESTION: {question}\n\n"
            f"Think step by step. Answer with the exact company name."
        ),
        response_model=SingleQA,
        model=model,
        temperature=0.0,
        max_tokens=16384,
        timeout=90,
    )
    if result:
        return _match_company_name(result.get("company_name", ""), company_names)
    return None


async def _answer_from_table(
    llm: LLMClient,
    question: str,
    companies: list[CompanyData],
    valid_names: list[str],
    model: str | None,
) -> str | None:
    """Answer a question using LLM with structured data table."""
    table = _format_data_table(companies)
    result = await llm.generate_chat(
        system_prompt=QA_TABLE_SYSTEM,
        user_prompt=(
            f"COMPANY DATA:\n{table}\n\n"
            f"QUESTION: {question}\n\n"
            f"Think step by step. Answer with the exact company name."
        ),
        response_model=SingleQA,
        model=model,
        temperature=0.0,
        max_tokens=4096,
        timeout=60,
    )
    if result:
        return _match_company_name(result.get("company_name", ""), valid_names)
    return None


async def _answer_all_from_doc(
    llm: LLMClient,
    doc: str,
    questions: list[str],
    company_names: list[str],
    model: str | None,
) -> list[str | None]:
    """Answer all questions from doc in parallel."""
    tasks = [
        _answer_from_doc(llm, doc, q, company_names, model)
        for q in questions
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    answers = []
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            logger.warning(f"Q{i+1} doc answer failed: {res}")
            answers.append(None)
        else:
            answers.append(res)
    return answers


# ── Stage 2: Constraint Parsing ──────────────────────────────────────────

async def _parse_constraints_llm(
    llm: LLMClient,
    constraints: list[str],
    answers: list[str | None],
    companies: list[CompanyData],
    model: str | None,
    max_retries: int = 2,
) -> ConstraintParseResponse:
    """Parse constraints via LLM with validation and retry."""
    # Build answers context
    qa_lines = []
    for i, ans in enumerate(answers):
        qa_lines.append(f"Q{i+1} = {ans or 'UNANSWERED'}")

    # Build company data context (only for answered companies)
    answered_names = {a for a in answers if a}
    company_lines = []
    for c in companies:
        if c.name in answered_names:
            company_lines.append(
                f"{c.name}: HQ={c.hq_city}, {c.hq_country} | "
                f"CEO={c.ceo_full_name} | emp={c.employees} | "
                f"Q1rev={int(c.q1_revenue_m)}M Q4rev={int(c.q4_revenue_m)}M"
            )

    constraints_text = "\n".join(f"C{i+1}: {c}" for i, c in enumerate(constraints))

    user_prompt = (
        f"ANSWERED QUESTIONS:\n{chr(10).join(qa_lines)}\n\n"
        f"COMPANY DATA (for answered companies):\n{chr(10).join(company_lines)}\n\n"
        f"CONSTRAINTS:\n{constraints_text}\n\n"
        f"Parse each constraint and compute all required values."
    )

    for attempt in range(max_retries + 1):
        if attempt > 0:
            user_prompt += f"\n\nPREVIOUS ERRORS (attempt {attempt}):\n" + "\n".join(issues)
            user_prompt += "\nPlease fix these errors."

        result = await llm.generate_chat(
            system_prompt=CONSTRAINT_SYSTEM,
            user_prompt=user_prompt,
            response_model=ConstraintParseResponse,
            model=model,
            temperature=0.0,
            max_tokens=4096,
            timeout=60,
        )

        if not result:
            logger.warning(f"Constraint parse attempt {attempt+1} returned None")
            continue

        try:
            parsed = ConstraintParseResponse.model_validate(result)
        except Exception as e:
            logger.warning(f"Constraint parse validation failed: {e}")
            continue

        # Programmatic validation
        issues = validate_constraint_parse(parsed)

        # Auto-fix prime if we can verify it
        if parsed.prime_value is not None and not is_prime(parsed.prime_value):
            corrected = next_prime(parsed.prime_value)
            logger.info(f"Auto-correcting prime: {parsed.prime_value} -> {corrected}")
            parsed.prime_value = corrected
            # Update in required_inclusions
            old_str = str(parsed.prime_value)
            parsed.required_inclusions = [
                str(corrected) if inc == old_str else inc
                for inc in parsed.required_inclusions
            ]
            issues = [i for i in issues if "not prime" not in i]

        # Auto-fix equation
        if parsed.equation and not validate_equation(parsed.equation):
            m = re.match(r"^(\d+)\+(\d+)=(\d+)$", parsed.equation.strip())
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                corrected_eq = f"{a}+{b}={a+b}"
                logger.info(f"Auto-correcting equation: {parsed.equation} -> {corrected_eq}")
                # Update in required_inclusions
                parsed.required_inclusions = [
                    corrected_eq if inc == parsed.equation else inc
                    for inc in parsed.required_inclusions
                ]
                parsed.equation = corrected_eq
                issues = [i for i in issues if "arithmetically wrong" not in i]

        if not issues:
            return parsed

        logger.warning(f"Constraint parse issues (attempt {attempt+1}): {issues}")

    # Return best effort
    logger.error("Constraint parsing failed validation after retries")
    return parsed


# ── Stage 3: Artifact Building ───────────────────────────────────────────

async def _build_artifact_llm(
    llm: LLMClient,
    parsed: ConstraintParseResponse,
    model: str | None,
    max_retries: int = 3,
) -> str | None:
    """Build artifact via LLM with programmatic validation and retry."""
    constraint_desc = []
    if parsed.word_count:
        constraint_desc.append(f"EXACTLY {parsed.word_count} words")
    if parsed.acrostic:
        constraint_desc.append(f"First 8 words must start with letters: {parsed.acrostic}")
    if parsed.required_inclusions:
        constraint_desc.append(f"Must contain: {parsed.required_inclusions}")
    if parsed.forbidden_letter:
        constraint_desc.append(f"Must NOT contain the letter '{parsed.forbidden_letter}' anywhere")

    base_prompt = (
        f"CONSTRAINTS:\n" + "\n".join(f"- {d}" for d in constraint_desc) + "\n\n"
        f"Build a single-line artifact satisfying ALL constraints.\n"
        f"Count your words carefully."
    )

    for attempt in range(max_retries + 1):
        user_prompt = base_prompt
        if attempt > 0:
            user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED:\n" + "\n".join(issues)
            user_prompt += f"\nPrevious artifact: {artifact}"
            user_prompt += "\nFix these issues. Count words carefully."

        result = await llm.generate_chat(
            system_prompt=ARTIFACT_SYSTEM,
            user_prompt=user_prompt,
            response_model=ArtifactResponse,
            model=model,
            temperature=0.1 * attempt,  # slight temp increase on retries
            max_tokens=2048,
            timeout=30,
        )

        if not result:
            logger.warning(f"Artifact build attempt {attempt+1} returned None")
            continue

        try:
            resp = ArtifactResponse.model_validate(result)
            artifact = resp.artifact.strip()
        except Exception as e:
            logger.warning(f"Artifact parse failed: {e}")
            continue

        # Remove any newlines
        artifact = artifact.replace("\n", " ").strip()

        issues = _validate_artifact_simple(artifact, parsed)
        if not issues:
            return artifact

        logger.warning(f"Artifact issues (attempt {attempt+1}): {issues}")

    logger.error("Artifact building failed after retries")
    return None


# ── Main solver ───────────────────────────────────────────────────────────

async def solve_challenge(
    llm: LLMClient,
    challenge: Challenge,
    model: str | None = None,
    large_model: str | None = None,
) -> tuple[list[tuple[str, frozenset[int]]], dict[int, set[int]]] | None:
    """Solve a challenge: Extract → Answer → Constrain → Build.

    Returns (candidates, constraint_q_map) or None if unsolvable.
    candidates = list of (artifact_str, frozenset of swapped Q numbers)
    """
    extract_model = model or large_model
    verify_model = large_model or model
    qa_model = large_model or model

    # Identify constraint-referenced questions
    crit_q_nums = set()
    for c in challenge.constraints:
        for m in re.finditer(r'Question\s*(\d+)', c, re.I):
            crit_q_nums.add(int(m.group(1)))
        for m in re.finditer(r'initials\(Q(\d+)\)', c, re.I):
            crit_q_nums.add(int(m.group(1)))
    crit_q_list = sorted(q for q in crit_q_nums if 1 <= q <= len(challenge.questions))
    logger.info(f"Constraint-critical questions: {crit_q_list}")

    # Stage 1: Extract companies + Answer from doc IN PARALLEL
    logger.info(
        f"Stage 1: Extracting {len(challenge.companies)} companies + "
        f"answering {len(challenge.questions)} questions..."
    )
    extract_task = asyncio.create_task(
        extract_all_companies(llm, challenge.doc, challenge.companies, model=extract_model)
    )
    doc_answers_task = asyncio.create_task(
        _answer_all_from_doc(llm, challenge.doc, challenge.questions, challenge.companies, qa_model)
    )

    # Await extraction
    companies = await extract_task
    if len(companies) < len(challenge.companies):
        logger.error(f"Extracted {len(companies)}/{len(challenge.companies)} — missing companies")
        if not companies:
            return None

    # Answer from extracted data table (cross-check)
    table_answers: list[str | None] = []
    table_tasks = [
        _answer_from_table(llm, q, companies, challenge.companies, model)
        for q in challenge.questions
    ]
    table_results = await asyncio.gather(*table_tasks, return_exceptions=True)
    for i, res in enumerate(table_results):
        if isinstance(res, Exception):
            logger.warning(f"Q{i+1} table answer failed: {res}")
            table_answers.append(None)
        else:
            table_answers.append(res)

    # Await doc answers
    doc_answers = await doc_answers_task

    # Merge answers: consensus between doc and table, or use whichever is available
    answers: list[str | None] = []
    disagreements: dict[int, str] = {}  # q_num -> alternative answer

    for i in range(len(challenge.questions)):
        doc_ans = doc_answers[i] if i < len(doc_answers) else None
        tbl_ans = table_answers[i] if i < len(table_answers) else None
        q_num = i + 1

        if doc_ans and tbl_ans:
            if doc_ans == tbl_ans:
                answers.append(doc_ans)
            else:
                # Disagreement — use doc answer (from raw text), track table as alt
                tag = " [CRIT]" if q_num in crit_q_nums else ""
                logger.warning(
                    f"  Q{q_num}{tag} DISAGREE: doc={doc_ans} vs table={tbl_ans}"
                )
                answers.append(doc_ans)
                disagreements[q_num] = tbl_ans
        elif doc_ans:
            answers.append(doc_ans)
        elif tbl_ans:
            answers.append(tbl_ans)
        else:
            answers.append(None)

    # Log answers
    for i, (q, ans) in enumerate(zip(challenge.questions, answers)):
        tag = " [CRIT]" if (i + 1) in crit_q_nums else ""
        logger.info(f"  Q{i+1}{tag}: {ans or 'UNANSWERED'} — {q[:80]}")

    if any(a is None for a in answers):
        missing = [i + 1 for i, a in enumerate(answers) if a is None]
        logger.error(f"Cannot answer questions: {missing}")
        return None

    # Stage 2: Verify constraint-critical companies
    critical_names = set()
    for c in challenge.constraints:
        for m_q in re.finditer(r'Question\s*(\d+)', c, re.I):
            q_num = int(m_q.group(1))
            if 1 <= q_num <= len(answers) and answers[q_num - 1]:
                critical_names.add(answers[q_num - 1])

    if critical_names:
        logger.info(f"Stage 2: Verifying {len(critical_names)} critical companies: {sorted(critical_names)}")
        verify_tasks = {
            name: asyncio.create_task(
                verify_critical_company(llm, challenge.doc, name, challenge.companies, verify_model)
            )
            for name in critical_names
        }

        for name, task in verify_tasks.items():
            try:
                vresult = await task
            except Exception as e:
                logger.warning(f"  Verification failed for {name}: {e}")
                continue

            if vresult is None:
                logger.warning(f"  Verification returned None for {name}")
                continue

            for ci, comp in enumerate(companies):
                if comp.name == name:
                    updates = {}
                    if vresult.hq_city and 1 < len(vresult.hq_city) < 50:
                        updates['hq_city'] = vresult.hq_city.title() if vresult.hq_city.isupper() else vresult.hq_city
                    if vresult.hq_country and 1 < len(vresult.hq_country) < 50:
                        updates['hq_country'] = vresult.hq_country.title() if vresult.hq_country.isupper() else vresult.hq_country
                    if vresult.ceo_full_name and ' ' in vresult.ceo_full_name.strip():
                        updates['ceo_full_name'] = vresult.ceo_full_name
                    if vresult.employees >= 100:
                        updates['employees'] = vresult.employees
                    if vresult.q1_revenue_m > 0:
                        updates['q1_revenue_m'] = round(vresult.q1_revenue_m)
                    if vresult.q4_revenue_m > 0:
                        updates['q4_revenue_m'] = round(vresult.q4_revenue_m)

                    changes = [
                        f"{f}: {getattr(comp, f)} -> {v}"
                        for f, v in updates.items()
                        if getattr(comp, f) != v
                    ]
                    if changes:
                        logger.info(f"  VERIFY {name}: {', '.join(changes)}")
                    companies[ci] = comp.model_copy(update=updates)
                    break

    # Stage 3: Parse constraints via LLM
    logger.info("Stage 3: Parsing constraints via LLM...")
    parsed = await _parse_constraints_llm(
        llm, challenge.constraints, answers, companies, verify_model,
    )
    logger.info(
        f"  word_count={parsed.word_count} acrostic='{parsed.acrostic}' "
        f"forbidden='{parsed.forbidden_letter}' prime={parsed.prime_value} "
        f"equation='{parsed.equation}' inclusions={parsed.required_inclusions}"
    )

    # Build constraint → Q number mapping for adaptive selection
    constraint_q_map: dict[int, set[int]] = {}
    for ci, c_text in enumerate(challenge.constraints):
        qs = set()
        for m_q in re.finditer(r'Question\s*(\d+)', c_text, re.I):
            qs.add(int(m_q.group(1)))
        for m_q in re.finditer(r'initials\(Q(\d+)\)', c_text, re.I):
            qs.add(int(m_q.group(1)))
        if qs:
            constraint_q_map[ci] = qs

    # Stage 4: Build artifact via LLM
    logger.info("Stage 4: Building artifact via LLM...")

    candidates: list[tuple[str, frozenset[int]]] = []
    seen: set[str] = set()

    def _add(art: str | None, swapped: frozenset[int]) -> None:
        if art and art not in seen:
            seen.add(art)
            candidates.append((art, swapped))

    # Primary candidate
    artifact = await _build_artifact_llm(llm, parsed, model)
    _add(artifact, frozenset())

    # Alternative candidates from disagreements
    if disagreements:
        logger.info(f"Stage 4b: Building {len(disagreements)} alternative candidates...")
        for q_num, alt_ans in disagreements.items():
            alt_answers = list(answers)
            alt_answers[q_num - 1] = alt_ans

            alt_parsed = await _parse_constraints_llm(
                llm, challenge.constraints, alt_answers, companies, model,
                max_retries=1,
            )
            alt_artifact = await _build_artifact_llm(llm, alt_parsed, model, max_retries=1)
            _add(alt_artifact, frozenset({q_num}))

    if not candidates:
        logger.error("No valid artifact candidates produced")
        return None

    # Append proposal vote to all candidates
    if challenge.proposal:
        vote, reasoning = await evaluate_proposal(llm, challenge.proposal)
        suffix = f"\nVOTE: {vote}\nREASONING: {reasoning}"
        candidates = [(c + suffix, s) for c, s in candidates]

    logger.info(f"Produced {len(candidates)} candidate artifact(s)")
    return candidates, constraint_q_map
