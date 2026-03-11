"""Load .env, validate, freeze config."""

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bankr_api: str
    coordinator_url: str
    llm_base_url: str
    llm_model: str
    llm_model_large: str
    max_consecutive_failures: int
    log_level: str
    pool_address: str | None
    no_tui: bool


def load_config() -> Config:
    load_dotenv()

    bankr_api = os.getenv("BANKR_API", "").strip()

    if not bankr_api:
        print("ERROR: Missing required env var: BANKR_API", file=sys.stderr)
        print("Run 'botcoin setup' or copy .env.example to .env and fill in the value.", file=sys.stderr)
        sys.exit(1)

    return Config(
        bankr_api=bankr_api,
        coordinator_url=os.getenv("COORDINATOR_URL", "https://coordinator.agentmoney.net").strip().rstrip("/"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://llm.bankr.bot").strip().rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "gemini-2.5-flash").strip(),
        llm_model_large=os.getenv("LLM_MODEL_LARGE", "gemini-2.5-pro").strip(),
        max_consecutive_failures=int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        pool_address=os.getenv("POOL_ADDRESS", "").strip() or None,
        no_tui=os.getenv("NO_TUI", "").strip().lower() in ("1", "true", "yes"),
    )
