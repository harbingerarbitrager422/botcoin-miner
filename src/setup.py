"""First-run setup wizard for BOTCOIN miner."""

from __future__ import annotations

import asyncio
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

# Available models on the Bankr LLM Gateway (https://bankr.bot/llm?tab=models)
# (model_id, provider, notes)
GATEWAY_MODELS: list[tuple[str, str, str]] = [
    ("gemini-2.5-flash", "Google", "fast & cheap — recommended for mining"),
    ("gemini-2.5-pro", "Google", "accurate — recommended for verification"),
    ("gemini-3-flash", "Google", ""),
    ("gemini-3-pro", "Google", ""),
    ("claude-haiku-4.5", "Anthropic", ""),
    ("claude-sonnet-4.5", "Anthropic", ""),
    ("claude-sonnet-4.6", "Anthropic", ""),
    ("claude-opus-4.5", "Anthropic", ""),
    ("claude-opus-4.6", "Anthropic", ""),
    ("gpt-5-nano", "OpenAI", ""),
    ("gpt-5-mini", "OpenAI", ""),
    ("gpt-5.2", "OpenAI", ""),
    ("gpt-5.2-codex", "OpenAI", ""),
    ("grok-4.1-fast", "xAI", ""),
    ("kimi-k2.5", "Moonshot", ""),
    ("qwen3-coder", "Alibaba", ""),
    ("qwen3.5-flash", "Alibaba", ""),
    ("qwen3.5-plus", "Alibaba", ""),
    ("deepseek-v3.2", "DeepSeek", ""),
]


def _ensure_env_file() -> str:
    """Ensure .env file exists, return its path."""
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("BANKR_API=\n")
        console.print("[dim]Created .env file[/dim]")
    return env_path


def _read_env(env_path: str) -> dict[str, str]:
    """Read .env file into dict."""
    vals = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    vals[key.strip()] = val.strip()
    return vals


def _write_env(env_path: str, vals: dict[str, str]) -> None:
    """Write dict back to .env, preserving comments."""
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    # Update existing keys
    written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in vals:
                new_lines.append(f"{key}={vals[key]}\n")
                written.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add new keys
    for key, val in vals.items():
        if key not in written:
            new_lines.append(f"{key}={val}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)


async def run_setup(config=None) -> bool:
    """Run the setup wizard. Returns True if setup completed successfully."""
    console.print(Panel("[bold]BOTCOIN Miner Setup[/bold]", border_style="blue"))

    # Step 1: .env file
    env_path = _ensure_env_file()
    env_vals = _read_env(env_path)

    # Step 2: API key
    api_key = env_vals.get("BANKR_API", "")
    if not api_key:
        console.print("\nYou need a Bankr API key. Get one at [link]https://bankr.bot/api[/link]")
        api_key = Prompt.ask("Enter your BANKR_API key")
        if not api_key.strip():
            console.print("[red]API key is required.[/red]")
            return False
        env_vals["BANKR_API"] = api_key.strip()
        _write_env(env_path, env_vals)
        console.print("[green]API key saved to .env[/green]")
    else:
        console.print(f"[green]API key found[/green]: {api_key[:8]}...")

    # Step 3: Validate key
    from .clients.bankr import BankrClient

    bankr = BankrClient(api_key.strip())
    try:
        me = await bankr.get_me()
        wallets = me.get("wallets", [])
        addr = "unknown"
        for w in wallets:
            if w.get("chain", "").lower() in ("base", "evm", "ethereum"):
                addr = w["address"]
                break
        if addr == "unknown" and wallets:
            addr = wallets[0].get("address", "unknown")
        if addr == "unknown" and "address" in me:
            addr = me["address"]
        console.print(f"[green]Wallet:[/green] {addr}")
    except Exception as e:
        console.print(f"[red]API key validation failed:[/red] {e}")
        console.print("Check your key and try again.")
        await bankr.close()
        return False

    # Step 4: LLM gateway health
    from .clients.llm import LLMClient

    llm_base = env_vals.get("LLM_BASE_URL", "https://llm.bankr.bot")
    model = env_vals.get("LLM_MODEL", "gemini-2.5-flash")

    llm = LLMClient(
        small_model=model,
        large_model=env_vals.get("LLM_MODEL_LARGE", "gemini-2.5-pro"),
        api_key=api_key.strip(),
        base_url=llm_base,
    )

    try:
        health = await llm.check_health()
        console.print(f"[green]LLM gateway healthy[/green]: {health.get('status', 'ok')}")
    except Exception as e:
        console.print(f"[yellow]LLM gateway health check failed:[/yellow] {e}")
        console.print("Mining may still work — gateway might not expose /health.")

    # Step 5: Model selection
    console.print("\n[bold]Model Selection[/bold]")

    # Try fetching live model list; fall back to built-in catalog
    model_ids: list[str] = []
    model_display: list[tuple[str, str, str]] = []  # (id, provider, notes)
    try:
        models_data = await llm.list_models()
        model_ids = sorted(
            m["id"] if isinstance(m, dict) else str(m)
            for m in models_data
        )
        # Build display from live data, enrich with known metadata
        known = {m[0]: m for m in GATEWAY_MODELS}
        for mid in model_ids:
            if mid in known:
                model_display.append(known[mid])
            else:
                model_display.append((mid, "", ""))
    except Exception:
        # Use built-in catalog
        model_display = list(GATEWAY_MODELS)
        model_ids = [m[0] for m in model_display]

    console.print(f"  {len(model_ids)} models available on the gateway "
                  "([link]https://bankr.bot/llm?tab=models[/link]):\n")

    from rich.table import Table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="cyan")
    table.add_column("Provider", style="dim")
    table.add_column("", style="green")  # notes

    for i, (mid, provider, notes) in enumerate(model_display, 1):
        table.add_row(str(i), mid, provider, notes)
    console.print(table)
    console.print()

    current_model = env_vals.get("LLM_MODEL", "gemini-2.5-flash")
    new_model = Prompt.ask(
        "Choose model",
        choices=model_ids,
        default=current_model if current_model in model_ids else model_ids[0],
    )
    if new_model != env_vals.get("LLM_MODEL"):
        env_vals["LLM_MODEL"] = new_model
        _write_env(env_path, env_vals)
        console.print(f"[green]Model set to {new_model}[/green]")

    # Step 6: Usage check
    try:
        usage = await llm.get_usage(days=1)
        cost = usage.get("total_cost", usage.get("totalCost", "?"))
        console.print(f"[dim]Recent usage (24h): ${cost}[/dim]")
    except Exception:
        pass

    # Step 7: Auto top-up
    console.print("\n[bold]LLM Credit Auto Top-Up[/bold]")
    console.print(
        "  LLM inference costs credits. Auto top-up spends USDC from your Bankr\n"
        "  wallet to buy more credits when your balance runs low.\n"
        "  Default: adds $25 in credits when balance drops below $5.\n"
        "  Requires USDC on Base in your Bankr wallet."
    )
    if Confirm.ask("Enable auto top-up?", default=False):
        from .credits import setup_auto_topup

        success = await setup_auto_topup(bankr, amount=25, threshold=5)
        if success:
            console.print("[green]Auto top-up enabled ($25 USDC from wallet when credits < $5)[/green]")
        else:
            console.print("[yellow]Auto top-up setup failed. You can set it up later at bankr.bot/llm[/yellow]")
    else:
        console.print(
            "[dim]Skipped. You can add credits manually at bankr.bot/llm?tab=credits\n"
            "or via CLI: bankr llm credits add 25[/dim]"
        )

    # Step 8: Staking
    console.print("\n[bold]Staking[/bold]")
    console.print(
        "  Staking BOTCOIN is required to mine. Higher tiers earn more rewards:\n"
        "    Tier 1:  25M BOTCOIN\n"
        "    Tier 2:  50M BOTCOIN\n"
        "    Tier 3: 100M BOTCOIN\n"
    )

    from .clients.coordinator import CoordinatorClient

    coordinator = CoordinatorClient(
        env_vals.get("COORDINATOR_URL", "https://coordinator.agentmoney.net").rstrip("/")
    )

    # Check wallet balances
    botcoin_balance = 0
    eth_balance = 0.0
    botcoin_usd = 0.0
    botcoin_price = 0.0
    try:
        balances_data = await bankr.get_balances()
        # Structure: {"balances": {"base": {"nativeBalance": "0.06", "tokenBalances": [...]}}}
        chains = balances_data.get("balances", {})
        base_data = chains.get("base", {})

        # ETH balance
        eth_balance = float(base_data.get("nativeBalance", "0"))
        eth_usd = base_data.get("nativeUsd", "0")

        console.print(f"  Wallet ETH:     [cyan]{eth_balance:.4f}[/cyan] (~${eth_usd})")

        # BOTCOIN token balance
        for tok in base_data.get("tokenBalances", []):
            token_info = tok.get("token", {})
            base_token = token_info.get("baseToken", {})
            symbol = base_token.get("symbol", "").upper()
            if symbol == "BOTCOIN":
                raw_balance = token_info.get("balance", "0")
                botcoin_balance = int(float(raw_balance))
                botcoin_usd = token_info.get("balanceUSD", 0)
                botcoin_price = base_token.get("price", 0)
                break

        if botcoin_balance > 0:
            console.print(f"  Wallet BOTCOIN: [cyan]{botcoin_balance:,}[/cyan] (~${botcoin_usd:.2f})")
        else:
            console.print("  Wallet BOTCOIN: [yellow]0[/yellow]")

    except Exception as e:
        console.print(f"  [dim]Could not fetch wallet balances: {e}[/dim]")

    # Check staking status via credits endpoint (staking info may be embedded)
    staked_whole = 0
    try:
        stake_info = await coordinator.get_stake_info(addr)
        staked_raw = int(stake_info.staked or "0")
        staked_whole = staked_raw // (10 ** 18) if staked_raw else 0
    except Exception:
        pass  # No staking info endpoint — rely on wallet balance

    if staked_whole > 0:
        if staked_whole >= 100_000_000:
            tier = "Tier 3"
        elif staked_whole >= 50_000_000:
            tier = "Tier 2"
        elif staked_whole >= 25_000_000:
            tier = "Tier 1"
        else:
            tier = "below Tier 1"
        console.print(f"  Staked:         [green]{staked_whole:,} BOTCOIN ({tier})[/green]")

    # Decide what to show/offer
    if staked_whole >= 25_000_000:
        console.print("  [green]You're staked and ready to mine![/green]")
    elif botcoin_balance >= 25_000_000:
        # Enough to stake — offer tiers
        tiers = []
        if botcoin_balance >= 100_000_000:
            tiers = [("100000000", "Tier 3 (100M)"), ("50000000", "Tier 2 (50M)"), ("25000000", "Tier 1 (25M)")]
        elif botcoin_balance >= 50_000_000:
            tiers = [("50000000", "Tier 2 (50M)"), ("25000000", "Tier 1 (25M)")]
        else:
            tiers = [("25000000", "Tier 1 (25M)")]

        console.print(f"\n  You have enough BOTCOIN to stake! Available tiers:")
        for amt, label in tiers:
            console.print(f"    [cyan]{label}[/cyan]")

        if Confirm.ask("  Stake now?", default=True):
            choices = [amt for amt, _ in tiers]
            labels = {amt: label for amt, label in tiers}
            stake_amount = Prompt.ask(
                "  Choose amount",
                choices=choices,
                default=choices[0],
            )
            console.print(f"  Staking {labels[stake_amount]}...")
            try:
                from .staking.staking import stake as do_stake
                await do_stake(coordinator, bankr, int(stake_amount))
                console.print(f"  [green]Staked {labels[stake_amount]} successfully![/green]")
            except Exception as e:
                console.print(f"  [red]Staking failed:[/red] {e}")
                console.print(f"  You can stake later: botcoin stake {choices[0]}")
        else:
            console.print(f"  [dim]You can stake later: botcoin stake {tiers[-1][0]}[/dim]")
    else:
        # Not enough BOTCOIN
        needed = 25_000_000 - botcoin_balance
        console.print(f"  [yellow]Need {needed:,} more BOTCOIN to reach Tier 1 (25M).[/yellow]")
        if botcoin_price > 0:
            cost_usd = needed * botcoin_price
            console.print(f"  Estimated cost: ~${cost_usd:.2f} USDC")
        console.print(
            "\n  To get BOTCOIN, swap via Bankr:\n"
            "    [cyan]bankr swap <amount> USDC to BOTCOIN[/cyan]\n"
            "  Or buy BOTCOIN on Base and transfer to your Bankr wallet:\n"
            f"    [dim]{addr}[/dim]"
        )

    await coordinator.close()
    await llm.close()
    await bankr.close()

    console.print(Panel("[bold green]Setup complete![/bold green]\nRun [cyan]botcoin mine[/cyan] to start mining.", border_style="green"))
    return True


def needs_setup() -> bool:
    """Check if first-run setup is needed."""
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return True
    env = _read_env(env_path)
    return not env.get("BANKR_API", "").strip()
