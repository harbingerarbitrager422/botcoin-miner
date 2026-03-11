"""CLI entry point (argparse subcommands)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from .config import load_config
from .logger import setup_logging

logger = logging.getLogger(__name__)


def _resolve_address(me: dict) -> str:
    if "wallets" in me and me["wallets"]:
        for w in me["wallets"]:
            chain = w.get("chain", "").lower()
            if chain in ("base", "evm", "ethereum"):
                return w["address"]
        return me["wallets"][0]["address"]
    if "address" in me:
        return me["address"]
    raise RuntimeError(f"Could not resolve wallet address: {me}")


async def cmd_setup(args, config=None):
    from .setup import run_setup

    await run_setup()


async def cmd_mine(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient
    from .auth.token_manager import TokenManager
    from .mining.loop import mining_loop
    from .shutdown import setup_shutdown

    # Override model if specified via CLI
    if args.model:
        # Create modified config with CLI model override
        from dataclasses import replace
        config = replace(config, llm_model=args.model)

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)

    try:
        me = await bankr.get_me()
        miner = _resolve_address(me)
        logger.info(f"Miner address: {miner}")

        pool = args.pool or config.pool_address
        target = pool or miner

        token_mgr = TokenManager(target, coordinator, bankr)

        shutdown_event = asyncio.Event()
        setup_shutdown(shutdown_event)

        # TUI setup
        display = None
        use_tui = not config.no_tui and not args.no_tui
        if use_tui:
            try:
                from .ui.display import MinerDisplay
                display = MinerDisplay()
            except ImportError:
                logger.info("rich not installed, falling back to plain logging")

        if display:
            with display:
                await mining_loop(config, coordinator, bankr, token_mgr, target, shutdown_event, display=display)
        else:
            await mining_loop(config, coordinator, bankr, token_mgr, target, shutdown_event)
    finally:
        await coordinator.close()
        await bankr.close()


async def cmd_stake(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient
    from .staking.staking import stake

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)
    try:
        await stake(coordinator, bankr, args.amount)
    finally:
        await coordinator.close()
        await bankr.close()


async def cmd_unstake(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient
    from .staking.staking import unstake

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)
    try:
        await unstake(coordinator, bankr)
    finally:
        await coordinator.close()
        await bankr.close()


async def cmd_withdraw(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient
    from .staking.staking import withdraw

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)
    try:
        await withdraw(coordinator, bankr)
    finally:
        await coordinator.close()
        await bankr.close()


async def cmd_claim(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient
    from .claiming.claim import claim_epochs
    from .claiming.bonus import check_and_claim_bonus

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)
    try:
        me = await bankr.get_me()
        miner = _resolve_address(me)
        pool = args.pool or config.pool_address

        if args.bonus:
            await check_and_claim_bonus(coordinator, bankr, args.epochs, pool=pool)
        else:
            await claim_epochs(
                coordinator, bankr, args.epochs, pool=pool, legacy=args.legacy,
                miner=miner,
            )
    finally:
        await coordinator.close()
        await bankr.close()


async def cmd_status(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)
    try:
        me = await bankr.get_me()
        miner = _resolve_address(me)
        print(f"Wallet: {miner}")

        epoch = await coordinator.get_epoch()
        remaining = epoch.nextEpochStartTimestamp - int(time.time())
        print(f"Current epoch: {epoch.epochId}")
        if epoch.prevEpochId is not None:
            print(f"Previous epoch: {epoch.prevEpochId}")
        print(f"Next epoch in: {remaining // 3600}h {(remaining % 3600) // 60}m")

        credits = await coordinator.get_credits(miner)
        print(f"Credits: {credits}")
    finally:
        await coordinator.close()
        await bankr.close()


async def cmd_claim_log(args, config):
    from .claiming.claim_log import read_claim_log

    entries = read_claim_log()
    if not entries:
        print("No claim history found.")
        return

    if args.epoch:
        entries = [e for e in entries if e.get("epochId") == str(args.epoch)]

    for e in entries:
        status = "OK" if e.get("success") else "FAIL"
        ts = e.get("timestamp", "?")[:19]
        eid = e.get("epochId", "?")
        ctype = e.get("type", "?")
        tx = e.get("txHash", "")
        err = e.get("error", "")
        reward = e.get("reward", "")

        line = f"[{ts}] epoch={eid} type={ctype:<8s} {status}"
        if tx:
            line += f" tx={tx}"
        if reward:
            line += f" reward={reward}"
        if err and not e.get("success"):
            line += f" err={err}"
        print(line)


async def cmd_test_challenge(args, config):
    from .clients.coordinator import CoordinatorClient
    from .clients.bankr import BankrClient
    from .auth.token_manager import TokenManager
    from .clients.llm import LLMClient
    from .solver.solver import solve_challenge
    import secrets

    # Override model if specified via CLI
    if args.model:
        from dataclasses import replace
        config = replace(config, llm_model=args.model)

    coordinator = CoordinatorClient(config.coordinator_url)
    bankr = BankrClient(config.bankr_api)
    llm = LLMClient(
        small_model=config.llm_model,
        large_model=config.llm_model_large,
        api_key=config.bankr_api,
        base_url=config.llm_base_url,
    )
    try:
        me = await bankr.get_me()
        miner = _resolve_address(me)
        logger.info(f"Miner: {miner}")

        token_mgr = TokenManager(miner, coordinator, bankr)
        token = await token_mgr.get_token()

        nonce = secrets.token_hex(16)
        challenge = await coordinator.get_challenge(miner, nonce, token)

        print(f"\n=== Challenge ===")
        print(f"Epoch: {challenge.epochId}")
        print(f"Challenge ID: {challenge.challengeId}")
        print(f"Credits/solve: {challenge.creditsPerSolve}")
        print(f"Companies: {len(challenge.companies)}")
        print(f"Questions: {len(challenge.questions)}")
        print(f"Constraints: {len(challenge.constraints)}")
        print(f"Doc length: {len(challenge.doc)} chars")

        print(f"\n--- Questions ---")
        for i, q in enumerate(challenge.questions):
            print(f"  Q{i+1}: {q}")

        print(f"\n--- Constraints ---")
        for i, c in enumerate(challenge.constraints):
            print(f"  C{i+1}: {c[:120]}{'...' if len(c) > 120 else ''}")

        print(f"\n--- Solving ---")
        result = await solve_challenge(
            llm, challenge,
            model=config.llm_model,
            large_model=config.llm_model_large,
        )
        if result:
            candidates, _ = result
            artifact = candidates[0][0] if candidates else None
            if artifact:
                print(f"\n=== Artifact ===")
                print(artifact)
                print(f"\nWord count: {len(artifact.split())}")
                print(f"Total candidates: {len(candidates)}")
            else:
                print("\nFailed to solve challenge")
        else:
            print("\nFailed to solve challenge")

    finally:
        await llm.close()
        await coordinator.close()
        await bankr.close()


def main():
    parser = argparse.ArgumentParser(prog="botcoin", description="BOTCOIN Miner CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # setup
    sub.add_parser("setup", help="First-run setup wizard")

    # mine
    p_mine = sub.add_parser("mine", help="Run mining loop")
    p_mine.add_argument("--pool", type=str, default=None, help="Pool contract address")
    p_mine.add_argument("--model", type=str, default=None, help="Override LLM model for this session")
    p_mine.add_argument("--no-tui", action="store_true", help="Disable TUI (plain logging)")

    # stake
    p_stake = sub.add_parser("stake", help="Approve + stake BOTCOIN")
    p_stake.add_argument("amount", type=int, help="Whole BOTCOIN to stake")

    # unstake
    sub.add_parser("unstake", help="Request unstake (24h cooldown)")

    # withdraw
    sub.add_parser("withdraw", help="Withdraw after cooldown")

    # claim
    p_claim = sub.add_parser("claim", help="Claim epoch rewards")
    p_claim.add_argument("epochs", type=str, help="Comma-separated epoch IDs")
    p_claim.add_argument("--bonus", action="store_true", help="Claim bonus rewards")
    p_claim.add_argument("--pool", type=str, default=None, help="Pool contract address")
    p_claim.add_argument("--legacy", action="store_true", help="Use legacy V1 claim")

    # status
    sub.add_parser("status", help="Show wallet, epoch, credits info")

    # claim-log
    p_clog = sub.add_parser("claim-log", help="View claim history")
    p_clog.add_argument("--epoch", type=int, default=None, help="Filter by epoch ID")

    # test-challenge
    p_test = sub.add_parser("test-challenge", help="Fetch + solve one challenge (no submit)")
    p_test.add_argument("--model", type=str, default=None, help="Override LLM model")

    args = parser.parse_args()

    # Setup doesn't need config
    if args.command == "setup":
        asyncio.run(cmd_setup(args))
        return

    # Auto-trigger setup if .env missing
    from .setup import needs_setup
    if needs_setup() and args.command in ("mine", "test-challenge"):
        print("First-run setup required. Running setup wizard...")
        asyncio.run(cmd_setup(args))
        print()

    config = load_config()
    setup_logging(config.log_level)

    cmd_map = {
        "mine": cmd_mine,
        "stake": cmd_stake,
        "unstake": cmd_unstake,
        "withdraw": cmd_withdraw,
        "claim": cmd_claim,
        "claim-log": cmd_claim_log,
        "status": cmd_status,
        "test-challenge": cmd_test_challenge,
    }

    try:
        asyncio.run(cmd_map[args.command](args, config))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
