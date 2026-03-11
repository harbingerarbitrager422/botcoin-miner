"""Lightweight post-LLM validation — sanity checks to trigger retries."""

from __future__ import annotations

import re

from .models import ConstraintParseResponse


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def next_prime(n: int) -> int:
    if n < 2:
        return 2
    candidate = n if n % 2 != 0 else n + 1
    while True:
        if is_prime(candidate):
            return candidate
        candidate += 2


def validate_equation(equation: str) -> bool:
    """Check that an A+B=C equation is arithmetically correct."""
    m = re.match(r"^(\d+)\+(\d+)=(\d+)$", equation.strip())
    if not m:
        return False
    a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return a + b == c


def validate_constraint_parse(parsed: ConstraintParseResponse) -> list[str]:
    """Validate parsed constraint values. Returns list of issues."""
    issues = []

    if parsed.word_count is not None and parsed.word_count <= 0:
        issues.append(f"Invalid word count: {parsed.word_count}")

    if parsed.prime_value is not None and not is_prime(parsed.prime_value):
        issues.append(f"Prime value {parsed.prime_value} is not prime")

    if parsed.equation and not validate_equation(parsed.equation):
        issues.append(f"Equation {parsed.equation} is arithmetically wrong")

    if parsed.forbidden_letter and len(parsed.forbidden_letter) != 1:
        issues.append(f"Forbidden letter should be single char: '{parsed.forbidden_letter}'")

    if parsed.acrostic and len(parsed.acrostic) != 8:
        issues.append(f"Acrostic should be 8 chars, got {len(parsed.acrostic)}: '{parsed.acrostic}'")

    return issues


def validate_artifact(artifact: str, parsed: ConstraintParseResponse) -> list[str]:
    """Validate a built artifact against constraints. Returns list of issues."""
    issues = []
    words = artifact.split()

    if parsed.word_count and len(words) != parsed.word_count:
        issues.append(f"Word count {len(words)} != {parsed.word_count}")

    if parsed.acrostic and len(words) >= 8:
        first8 = "".join(w[0] for w in words[:8]).upper()
        if first8 != parsed.acrostic.upper():
            issues.append(f"Acrostic '{first8}' != '{parsed.acrostic}'")

    artifact_lower = artifact.lower()
    for req in parsed.required_inclusions:
        if req.lower() not in artifact_lower:
            issues.append(f"Missing required: '{req}'")

    if parsed.forbidden_letter and parsed.forbidden_letter.lower() in artifact_lower:
        issues.append(f"Contains forbidden letter '{parsed.forbidden_letter}'")

    if "\n" in artifact:
        issues.append("Contains newline")

    return issues
