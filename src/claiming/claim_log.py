"""Persistent JSON-lines log for all claim and bonus claim activity."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CLAIM_LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "claims")


def _ensure_dir():
    os.makedirs(CLAIM_LOGS_DIR, exist_ok=True)


def log_claim_attempt(
    epoch_id: int | str,
    claim_type: str,  # "regular", "bonus", "legacy"
    success: bool,
    tx_hash: str | None = None,
    error: str | None = None,
    reward: str | None = None,
    extra: dict | None = None,
) -> None:
    """Append one claim event to the JSONL log file."""
    _ensure_dir()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epochId": str(epoch_id),
        "type": claim_type,
        "success": success,
        "txHash": tx_hash,
        "error": error,
        "reward": reward,
    }
    if extra:
        entry.update(extra)

    log_file = os.path.join(CLAIM_LOGS_DIR, "claims.jsonl")
    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.debug(f"Failed to write claim log: {e}")


def read_claim_log() -> list[dict]:
    """Read all claim log entries."""
    log_file = os.path.join(CLAIM_LOGS_DIR, "claims.jsonl")
    if not os.path.exists(log_file):
        return []
    entries = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries
