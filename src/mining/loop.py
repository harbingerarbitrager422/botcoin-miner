"""Main mining loop orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone

from ..auth.token_manager import TokenManager
from ..clients.coordinator import CoordinatorClient, CoordinatorAPIError
from ..clients.bankr import BankrClient
from ..clients.llm import LLMClient, InsufficientCreditsError
from ..claiming.auto_claim import auto_claim_epoch
from ..config import Config
from ..credits import get_usage, add_credits
from ..errors import (
    Action, ClassifiedError, StopError, ReauthError, NewChallengeError,
)
from ..retry import with_retry
from ..solver.solver import solve_challenge
from .receipt import post_receipt

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")


def _save_challenge_log(challenge, artifact, result, error=None):
    """Persist challenge data and outcome to logs/ for debugging."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        cid = challenge.challengeId[:12]
        passed = result.pass_ if result else False
        tag = "pass" if passed else "fail"
        fname = f"{ts}_{cid}_{tag}.json"

        entry = {
            "timestamp": ts,
            "epochId": challenge.epochId,
            "challengeId": challenge.challengeId,
            "companies": challenge.companies,
            "questions": challenge.questions,
            "constraints": challenge.constraints,
            "doc_length": len(challenge.doc),
            "doc": challenge.doc,
            "artifact": artifact,
            "passed": passed,
            "failedConstraintIndices": result.failedConstraintIndices if result else None,
            "error": error,
        }
        with open(os.path.join(LOGS_DIR, fname), "w") as f:
            json.dump(entry, f, indent=2)
    except Exception as e:
        logging.getLogger(__name__).debug(f"Failed to save challenge log: {e}")

logger = logging.getLogger(__name__)

CHALLENGE_COOLDOWN = 65  # seconds between challenge requests (server enforces 60s)
CREDIT_CHECK_INTERVAL = 15 * 60  # check credits every 15 minutes
CREDIT_CHECK_SOLVES = 10  # or every 10 solves


async def _safe_auto_claim(
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    epoch_id: int,
    pool: str | None,
    miner: str | None = None,
) -> None:
    """Fire-and-forget wrapper so claim errors never crash the mining loop."""
    try:
        await auto_claim_epoch(coordinator, bankr, epoch_id, pool, miner=miner)
    except Exception as e:
        logger.error(f"Auto-claim task for epoch {epoch_id} failed: {e}")


async def mining_loop(
    config: Config,
    coordinator: CoordinatorClient,
    bankr: BankrClient,
    token_mgr: TokenManager,
    miner: str,
    shutdown_event: asyncio.Event,
    display=None,
) -> None:
    llm = LLMClient(
        small_model=config.llm_model,
        large_model=config.llm_model_large,
        api_key=config.bankr_api,
        base_url=config.llm_base_url,
    )

    consecutive_failures = 0
    total_solves = 0
    total_attempts = 0
    pool = config.pool_address
    use_pool = pool is not None
    last_challenge_time = 0.0
    last_credit_check = 0.0
    solves_since_credit_check = 0

    current_epoch: int | None = None
    mined_epochs: set[int] = set()
    claim_tasks: dict[int, asyncio.Task] = {}

    def _log(msg: str, level: str = "info") -> None:
        if display:
            display.log(msg, level)
        else:
            getattr(logger, level)(msg)

    def _status(msg: str) -> None:
        if display:
            display.update_status(msg)
        logger.info(msg)

    if display:
        display.wallet = miner
        display.model = config.llm_model

    _log(f"Starting mining loop (miner={miner}, pool={pool or 'none'})")

    try:
        while not shutdown_event.is_set():
            if consecutive_failures >= config.max_consecutive_failures:
                _log(
                    f"Stopping: {consecutive_failures} consecutive failures.",
                    "error",
                )
                break

            try:
                # 1. Respect rate limit
                elapsed = time.monotonic() - last_challenge_time
                if elapsed < CHALLENGE_COOLDOWN and last_challenge_time > 0:
                    wait = CHALLENGE_COOLDOWN - elapsed
                    _status(f"Cooldown {wait:.0f}s...")
                    for _ in range(int(wait)):
                        if shutdown_event.is_set():
                            break
                        await asyncio.sleep(1)
                    if shutdown_event.is_set():
                        break

                # 2. Periodic credit check
                now = time.monotonic()
                if (now - last_credit_check > CREDIT_CHECK_INTERVAL
                        or solves_since_credit_check >= CREDIT_CHECK_SOLVES):
                    try:
                        usage = await get_usage(llm, days=1)
                        cost = usage.get("total_cost", usage.get("totalCost", "?"))
                        if display:
                            display.update_credits(f"${cost}")
                        _log(f"Usage (24h): ${cost}")
                    except Exception:
                        pass
                    last_credit_check = now
                    solves_since_credit_check = 0

                # 3. Get challenge
                nonce = secrets.token_hex(16)
                token = await token_mgr.get_token()

                def _classify_coord(exc: Exception) -> ClassifiedError:
                    if isinstance(exc, CoordinatorAPIError):
                        return exc.classified
                    return ClassifiedError(Action.RETRY, str(exc))

                _status("Fetching challenge...")

                try:
                    challenge = await with_retry(
                        lambda: coordinator.get_challenge(pool or miner, nonce, token),
                        _classify_coord,
                        max_attempts=5,
                        backoff=[30, 60, 60, 90, 120],
                    )
                except ReauthError:
                    token_mgr.invalidate()
                    token = await token_mgr.get_token()
                    await asyncio.sleep(5)
                    challenge = await with_retry(
                        lambda: coordinator.get_challenge(pool or miner, nonce, token),
                        _classify_coord,
                        max_attempts=3,
                        backoff=[60, 90, 120],
                    )
                except StopError:
                    _log("Challenge rate limited, waiting 120s before retry...", "warning")
                    await asyncio.sleep(120)
                    continue

                last_challenge_time = time.monotonic()
                if display:
                    display.update_epoch(challenge.epochId)
                _log(
                    f"Challenge: epoch={challenge.epochId} "
                    f"id={challenge.challengeId[:12]}... "
                    f"credits/solve={challenge.creditsPerSolve}"
                )

                # Epoch transition detection
                if current_epoch is not None and challenge.epochId != current_epoch:
                    prev = current_epoch
                    _log(f"Epoch transition: {prev} -> {challenge.epochId}")
                    if prev in mined_epochs and prev not in claim_tasks:
                        task = asyncio.create_task(
                            _safe_auto_claim(coordinator, bankr, prev, pool, miner=miner),
                            name=f"auto-claim-{prev}",
                        )
                        claim_tasks[prev] = task
                current_epoch = challenge.epochId

                # 4. Solve
                _status(f"Solving challenge {challenge.challengeId[:12]}...")
                total_attempts += 1
                solve_result = await solve_challenge(
                    llm, challenge,
                    model=config.llm_model,
                    large_model=config.llm_model_large,
                )
                if not solve_result or not solve_result[0]:
                    consecutive_failures += 1
                    _log(
                        f"Solve failed ({consecutive_failures}/{config.max_consecutive_failures})",
                        "warning",
                    )
                    if display:
                        display.update_solve_stats(total_attempts, total_solves)
                    _save_challenge_log(challenge, None, None, error="solve_failed")
                    continue

                candidates_with_meta, constraint_q_map = solve_result

                # 5. Submit candidates
                token = await token_mgr.get_token()
                result = None
                artifact = None
                challenge_stale = False

                _status("Submitting...")
                artifact = candidates_with_meta[0][0]
                try:
                    result = await with_retry(
                        lambda c=artifact: coordinator.submit(
                            pool or miner, challenge.challengeId, c, nonce,
                            token, pool=use_pool,
                        ),
                        _classify_coord,
                        max_attempts=3,
                    )
                except ReauthError:
                    token_mgr.invalidate()
                    token = await token_mgr.get_token()
                    try:
                        result = await coordinator.submit(
                            pool or miner, challenge.challengeId, artifact, nonce,
                            token, pool=use_pool,
                        )
                    except (NewChallengeError, CoordinatorAPIError):
                        challenge_stale = True
                except NewChallengeError:
                    challenge_stale = True

                if challenge_stale:
                    _log("Stale challenge (404), fetching new one", "warning")
                    consecutive_failures += 1
                    continue

                if result and result.pass_:
                    _log(f"Candidate 1/{len(candidates_with_meta)} PASSED!", "success")
                elif result and not result.pass_:
                    failed = result.failedConstraintIndices or []
                    _log(
                        f"Candidate 1/{len(candidates_with_meta)} failed constraints {failed}",
                        "warning",
                    )

                # Try adaptive alternate candidate
                if result and not result.pass_ and not challenge_stale and len(candidates_with_meta) > 1:
                    failed_set = set(failed)
                    failed_constraint_qs: list[set[int]] = []
                    for fc_idx in failed:
                        qs = constraint_q_map.get(fc_idx, set())
                        if qs:
                            failed_constraint_qs.append(qs)

                    passing_constraint_qs: list[set[int]] = []
                    for ci, qs in constraint_q_map.items():
                        if ci not in failed_set:
                            passing_constraint_qs.append(qs)

                    best_idx = 1
                    best_score = (-1, 999, 999)
                    for idx in range(1, len(candidates_with_meta)):
                        _, swapped_qs = candidates_with_meta[idx]
                        addressed = sum(1 for qs in failed_constraint_qs if swapped_qs & qs)
                        at_risk = sum(1 for qs in passing_constraint_qs if swapped_qs & qs)
                        score = (addressed, -at_risk, -len(swapped_qs))
                        if score > best_score:
                            best_score = score
                            best_idx = idx

                    best_addressed = best_score[0]
                    best_at_risk = -best_score[1]

                    submit_adaptive = best_addressed > 0 and best_at_risk <= best_addressed
                    if submit_adaptive:
                        artifact = candidates_with_meta[best_idx][0]
                        try:
                            result = await with_retry(
                                lambda c=artifact: coordinator.submit(
                                    pool or miner, challenge.challengeId, c, nonce,
                                    token, pool=use_pool,
                                ),
                                _classify_coord,
                                max_attempts=3,
                            )
                        except ReauthError:
                            token_mgr.invalidate()
                            token = await token_mgr.get_token()
                            try:
                                result = await coordinator.submit(
                                    pool or miner, challenge.challengeId, artifact, nonce,
                                    token, pool=use_pool,
                                )
                            except (NewChallengeError, CoordinatorAPIError):
                                challenge_stale = True
                        except NewChallengeError:
                            challenge_stale = True

                        if not challenge_stale and result and result.pass_:
                            _log(f"Alternate candidate {best_idx+1} PASSED!", "success")
                        elif not challenge_stale and result:
                            failed2 = result.failedConstraintIndices or []
                            _log(f"Alternate candidate {best_idx+1} failed {failed2}", "warning")

                if challenge_stale:
                    _log("Stale challenge (404), fetching new one", "warning")
                    consecutive_failures += 1
                    continue

                if not result or not result.pass_:
                    consecutive_failures += 1
                    _log(
                        f"All candidates failed ({consecutive_failures}/{config.max_consecutive_failures})",
                        "warning",
                    )
                    if display:
                        display.update_solve_stats(total_attempts, total_solves)
                    _save_challenge_log(challenge, artifact, result)
                    continue

                _save_challenge_log(challenge, artifact, result)

                # 6. Post receipt
                if result.transaction:
                    receipt_result = await post_receipt(bankr, result.transaction)
                    if receipt_result.success:
                        total_solves += 1
                        consecutive_failures = 0
                        solves_since_credit_check += 1
                        mined_epochs.add(challenge.epochId)
                        _log(
                            f"Receipt posted! tx={receipt_result.transactionHash} "
                            f"total_solves={total_solves} epoch={challenge.epochId}",
                            "success",
                        )
                    else:
                        _log(f"Receipt failed: {receipt_result}", "error")
                        consecutive_failures += 1
                else:
                    _log("No transaction in submit response", "warning")
                    total_solves += 1
                    consecutive_failures = 0
                    solves_since_credit_check += 1
                    mined_epochs.add(challenge.epochId)

                if display:
                    display.update_solve_stats(total_attempts, total_solves)

            except InsufficientCreditsError:
                _log("Insufficient LLM credits! Attempting to add credits...", "error")
                try:
                    success = await add_credits(bankr, amount=25)
                    if success:
                        _log("Credits added, resuming...", "success")
                        continue
                except Exception:
                    pass
                _log(
                    "Could not add credits. Fund your account at bankr.bot/llm",
                    "error",
                )
                break
            except StopError as e:
                _log(f"Fatal: {e}", "error")
                break
            except Exception as e:
                consecutive_failures += 1
                logger.exception(
                    f"Unexpected error ({consecutive_failures}/{config.max_consecutive_failures}): {e}"
                )

    finally:
        await llm.close()

    # Wait for pending auto-claim tasks
    if claim_tasks:
        pending = [t for t in claim_tasks.values() if not t.done()]
        if pending:
            _log(f"Waiting for {len(pending)} pending auto-claim task(s)...")
            await asyncio.gather(*pending, return_exceptions=True)

    _log(
        f"Mining loop ended. Total solves: {total_solves}, "
        f"mined epochs: {sorted(mined_epochs)}"
    )
