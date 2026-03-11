"""Per-company LLM extraction: full doc + company name -> CompanyData."""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, model_validator

from ..clients.llm import LLMClient
from .prompts import EXTRACT_SYSTEM, VERIFY_SYSTEM

logger = logging.getLogger(__name__)


class CompanyData(BaseModel):
    name: str
    hq_city: str
    hq_country: str
    sector: str
    ceo_full_name: str
    employees: int
    is_public: bool
    founding_year: int
    ipo_year: int | None = None
    q1_revenue_m: float
    q1_growth_pct: float
    q2_revenue_m: float
    q2_growth_pct: float
    q3_revenue_m: float
    q3_growth_pct: float
    q4_revenue_m: float
    q4_growth_pct: float
    debt_to_equity: float
    satisfaction_rating: float

    @model_validator(mode="before")
    @classmethod
    def clean_numeric_strings(cls, data):
        """Strip trailing periods and coerce numeric strings."""
        if not isinstance(data, dict):
            return data
        for key, val in data.items():
            if isinstance(val, str):
                cleaned = val.rstrip(".").strip()
                try:
                    data[key] = int(cleaned)
                    continue
                except ValueError:
                    pass
                try:
                    data[key] = float(cleaned)
                except ValueError:
                    data[key] = cleaned
        return data


async def _extract_one(
    llm: LLMClient,
    doc: str,
    company_name: str,
    all_companies: list[str],
    model: str | None = None,
) -> CompanyData | None:
    """Extract one company's data from the full document via LLM."""
    companies_str = ", ".join(all_companies)

    result = await llm.generate_chat(
        system_prompt=EXTRACT_SYSTEM,
        user_prompt=(
            f"Extract all data for: {company_name}\n\n"
            f"All 25 companies in this document: {companies_str}\n\n"
            f"DOCUMENT:\n{doc}"
        ),
        response_model=CompanyData,
        model=model,
        temperature=0.0,
        max_tokens=8192,
        timeout=60,
    )
    if result is None:
        return None

    try:
        data = CompanyData.model_validate(result)
    except (ValueError, TypeError) as e:
        logger.warning(f"{company_name}: validation failed ({e}), retrying cleanup")
        for k, v in result.items():
            if isinstance(v, str):
                cleaned = v.rstrip(".").strip()
                try:
                    result[k] = int(cleaned)
                    continue
                except ValueError:
                    pass
                try:
                    result[k] = float(cleaned)
                except ValueError:
                    pass
        try:
            data = CompanyData.model_validate(result)
        except Exception:
            logger.error(f"{company_name}: validation failed after cleanup")
            return None

    # Normalize name to match input
    if data.name != company_name:
        data = data.model_copy(update={"name": company_name})
    # Fix ipo_year for private companies
    if not data.is_public and data.ipo_year is not None and data.ipo_year <= 0:
        data = data.model_copy(update={"ipo_year": None})
    # Round revenues to whole millions
    data = data.model_copy(update={
        "q1_revenue_m": round(data.q1_revenue_m),
        "q2_revenue_m": round(data.q2_revenue_m),
        "q3_revenue_m": round(data.q3_revenue_m),
        "q4_revenue_m": round(data.q4_revenue_m),
    })

    return data


async def extract_all_companies(
    llm: LLMClient,
    doc: str,
    companies: list[str],
    model: str | None = None,
) -> list[CompanyData]:
    """Extract all companies in parallel, retry failures once."""

    tasks = [_extract_one(llm, doc, name, companies, model) for name in companies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    extracted: dict[str, CompanyData] = {}
    failed: list[str] = []

    for name, res in zip(companies, results):
        if isinstance(res, Exception):
            logger.warning(f"Extraction error for {name}: {res}")
            failed.append(name)
        elif res is None:
            logger.warning(f"Extraction returned None for {name}")
            failed.append(name)
        else:
            extracted[name] = res

    # Retry failures
    if failed:
        logger.warning(f"Retrying {len(failed)} failed extractions...")
        retry_tasks = [_extract_one(llm, doc, name, companies, model) for name in failed]
        retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
        for name, res in zip(failed, retry_results):
            if isinstance(res, Exception) or res is None:
                logger.error(f"Retry also failed for {name}")
            else:
                extracted[name] = res

    # Return in original order
    result = []
    for name in companies:
        if name in extracted:
            result.append(extracted[name])
        else:
            logger.error(f"No data extracted for {name}")
    return result


# ── Verification re-extraction for constraint-critical fields ──────────────

class CriticalFields(BaseModel):
    """Focused extraction of constraint-critical fields with evidence."""
    hq_city: str
    hq_country: str
    ceo_full_name: str
    employees: int
    q1_revenue_m: float
    q4_revenue_m: float
    q1_evidence: str
    q4_evidence: str
    employees_evidence: str

    @model_validator(mode="before")
    @classmethod
    def clean_numeric_strings(cls, data):
        if not isinstance(data, dict):
            return data
        for key, val in data.items():
            if isinstance(val, str):
                cleaned = val.rstrip(".").strip()
                try:
                    data[key] = int(cleaned)
                    continue
                except ValueError:
                    pass
                try:
                    data[key] = float(cleaned)
                except ValueError:
                    data[key] = cleaned
        return data


async def verify_critical_company(
    llm: LLMClient,
    doc: str,
    company_name: str,
    all_companies: list[str],
    model: str | None = None,
) -> CriticalFields | None:
    """Focused re-extraction of constraint-critical fields with evidence."""
    companies_str = ", ".join(all_companies)
    result = await llm.generate_chat(
        system_prompt=VERIFY_SYSTEM,
        user_prompt=(
            f"Find and verify these EXACT values for: {company_name}\n\n"
            f"1. Headquarters city\n"
            f"2. Headquarters country\n"
            f"3. CEO/President full name (first and last)\n"
            f"4. Total employee count (exact integer)\n"
            f"5. Q1 (first/opening quarter) revenue in MILLIONS (integer)\n"
            f"6. Q4 (fourth/closing/final quarter) revenue in MILLIONS (integer)\n"
            f"7-9. For Q1 revenue, Q4 revenue, and employee count, quote the "
            f"exact text from the document where you found each value.\n\n"
            f"All 25 companies in this document: {companies_str}\n\n"
            f"DOCUMENT:\n{doc}"
        ),
        response_model=CriticalFields,
        model=model,
        temperature=0.0,
        max_tokens=16384,
        timeout=60,
    )
    if result:
        try:
            return CriticalFields.model_validate(result)
        except Exception as e:
            logger.warning(f"Verification parse failed for {company_name}: {e}")
            return None
    return None
