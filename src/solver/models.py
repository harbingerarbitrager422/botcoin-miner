"""Pydantic response models for LLM solver stages."""

from __future__ import annotations

from pydantic import BaseModel


class SingleQA(BaseModel):
    company_name: str
    reasoning: str


class AllQAResponse(BaseModel):
    answers: list[SingleQA]


class ConstraintParseResponse(BaseModel):
    word_count: int | None = None
    required_inclusions: list[str] = []
    acrostic: str = ""
    forbidden_letter: str = ""
    prime_value: int | None = None
    equation: str = ""
    reasoning: str = ""


class ArtifactResponse(BaseModel):
    artifact: str
    reasoning: str = ""
