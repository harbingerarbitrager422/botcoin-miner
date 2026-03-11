# BOTCOIN Miner

Open-source BOTCOIN mining CLI for Base. Solves hybrid NLP challenges using LLM-powered extraction, question answering, constraint parsing, and artifact generation — all routed through the Bankr LLM Gateway.

## Prerequisites

- **Python 3.10+**
- **Bankr account** with Agent API enabled — [bankr.bot/api](https://bankr.bot/api)
- **ETH on Base** for gas (~$2 worth)
- **25M+ BOTCOIN** for staking (required to mine)

## Setup

### Quick Start (Interactive Wizard)

```bash
git clone https://github.com/harbingerarbitrager422/botcoin-miner && cd botcoin_pub
uv venv && source .venv/bin/activate
uv pip install -e .
botcoin setup
```

The setup wizard will walk you through everything: API key, LLM gateway health check, model selection, and optional auto top-up for LLM credits.

### Manual Setup

#### 1. Create a virtual environment (recommended)

Using [uv](https://docs.astral.sh/uv/) (fast, recommended):

```bash
uv venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

Or with standard `venv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### 2. Install the package

```bash
# With uv (faster)
uv pip install -e .

# Or with pip
pip install -e .
```

This installs the `botcoin` CLI command along with all dependencies (`httpx`, `pydantic`, `python-dotenv`, `rich`).

#### 3. Create your `.env` file

```bash
cp .env.example .env
```

#### 4. Get your Bankr API key

1. Go to [bankr.bot/api](https://bankr.bot/api)
2. Sign up / log in
3. Enable **Agent API**
4. Disable **read-only** mode (the miner needs to sign transactions)
5. Copy your API key

#### 5. Configure `.env`

Open `.env` and set your API key:

```
BANKR_API=your_api_key_here
```

That's the only required variable. Everything else has sensible defaults.

#### 6. Fund your Bankr wallet

Your Bankr agent wallet needs:
- **ETH on Base** for gas fees (~$2 is enough to get started)
- **USDC on Base** for LLM credits (see next step)
- **BOTCOIN tokens** for staking (minimum 25M for Tier 1)

Fund your wallet via the Bankr dashboard or by transferring directly. Find your wallet address with:

```bash
botcoin status
```

#### 7. Fund LLM credits

The miner uses the Bankr LLM Gateway for inference. Each solve attempt costs LLM credits (~$0.01–0.05 with `gemini-2.5-flash`). Credits are purchased with **USDC from your Bankr wallet on Base**.

**Add credits manually:**
- **Dashboard**: [bankr.bot/llm?tab=credits](https://bankr.bot/llm?tab=credits)
- **CLI**: `bankr llm credits add 25` (spends $25 USDC → $25 in LLM credits)

**Auto top-up (recommended):**
The setup wizard (`botcoin setup`) can enable automatic top-up. When your LLM credit balance drops below $5, Bankr will automatically spend $25 USDC from your wallet to buy more credits — so mining never stalls. This requires USDC on Base in your Bankr wallet.

You can also configure this manually:
```bash
bankr llm credits auto --enable --amount 25 --threshold 5 --tokens USDC
```

#### 8. Stake BOTCOIN

Staking is required to mine. There are three tiers:

| Tier | Amount | Benefit |
|------|--------|---------|
| Tier 1 | 25M BOTCOIN | Base mining rewards |
| Tier 2 | 50M BOTCOIN | Higher rewards |
| Tier 3 | 100M BOTCOIN | Maximum rewards |

The setup wizard (`botcoin setup`) will check your wallet balance, show your current staking status, and offer to stake for you interactively.

**If you don't have BOTCOIN yet**, swap via the Bankr CLI:

```bash
bankr swap <amount> USDC to BOTCOIN
```

Or buy BOTCOIN on Base and transfer to your Bankr wallet address.

**Stake manually:**

```bash
botcoin stake 25000000   # Tier 1
botcoin stake 50000000   # Tier 2
botcoin stake 100000000  # Tier 3
```

#### 9. Start mining

```bash
botcoin mine
```

The miner will display a live TUI showing your wallet, epoch, solve stats, and LLM activity log.

## Commands

```
botcoin setup                          # First-run setup wizard
botcoin mine [options]                  # Run mining loop
botcoin stake <amount>                  # Approve + stake (whole BOTCOIN)
botcoin unstake                         # Request unstake (24h cooldown)
botcoin withdraw                        # Withdraw after cooldown
botcoin claim <epochs> [--bonus] [--pool <addr>] [--legacy]
botcoin status                          # Wallet, epoch, credits info
botcoin claim-log [--epoch <id>]        # View claim history
botcoin test-challenge [--model <name>] # Fetch + solve one challenge (no submit)
```

### Mining options

| Flag | Description |
|------|-------------|
| `--pool <addr>` | Mine to a pool contract address |
| `--model <name>` | Override LLM model for this session |
| `--no-tui` | Disable rich TUI, use plain log output |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BANKR_API` | **Yes** | — | Bankr API key (used for wallet, transactions, and LLM) |
| `COORDINATOR_URL` | No | `https://coordinator.agentmoney.net` | Challenge coordinator endpoint |
| `LLM_BASE_URL` | No | `https://llm.bankr.bot` | Bankr LLM Gateway base URL |
| `LLM_MODEL` | No | `gemini-2.5-flash` | Primary model (fast, cheap) |
| `LLM_MODEL_LARGE` | No | `gemini-2.5-pro` | Verification model (more accurate) |
| `MAX_CONSECUTIVE_FAILURES` | No | `5` | Stop after N consecutive solve failures |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `POOL_ADDRESS` | No | — | Default pool address for mining |
| `NO_TUI` | No | `false` | Disable TUI globally (`true`/`1`/`yes`) |

## Models

The miner uses two model slots:

- **Primary** (`LLM_MODEL`): Used for bulk extraction and artifact building. Default: `gemini-2.5-flash` — fast and cost-effective.
- **Verification** (`LLM_MODEL_LARGE`): Used for constraint-critical verification and question answering. Default: `gemini-2.5-pro` — better reasoning.

All models available on the Bankr LLM Gateway work, but Gemini models are recommended for this workload due to their large context windows (1M tokens) and cost efficiency.

Override for a single session:

```bash
botcoin mine --model gemini-2.5-pro
botcoin test-challenge --model gemini-2.5-flash
```

## How It Works

The miner solves challenges in a 4-stage LLM pipeline:

1. **Extract + Answer** (parallel): Extract structured data for all 25 companies, and answer all questions from the raw document — both via LLM. Cross-check answers against a structured data table.
2. **Verify**: Re-extract constraint-critical company data with a more accurate model for precision.
3. **Parse Constraints**: LLM parses constraint text into structured values (word count, acrostic, forbidden letter, prime, equation). Programmatic validation catches arithmetic errors and triggers retries.
4. **Build Artifact**: LLM generates a single-line artifact satisfying all constraints. Programmatic validation checks word count, acrostic, inclusions, and forbidden letter — retries with error feedback on failure.

## Claiming Rewards

After an epoch ends, claim your mining rewards:

```bash
# Claim specific epochs
botcoin claim 17,18,19

# Claim bonus rewards
botcoin claim 17 --bonus

# Claim via pool
botcoin claim 17,18 --pool 0x...
```

The miner automatically attempts to claim rewards when it detects an epoch transition during mining.

## Troubleshooting

**"Missing required env var: BANKR_API"**
Run `botcoin setup` or create `.env` with your API key.

**"Insufficient LLM credits"**
Add credits at [bankr.bot/llm](https://bankr.bot/llm?tab=credits) or enable auto top-up via the setup wizard.

**Solve failures / low pass rate**
- Try a more capable model: `--model gemini-2.5-pro`
- Check `logs/` directory for detailed challenge data and failure reasons
- Set `LOG_LEVEL=DEBUG` for verbose LLM interaction logs

**TUI not showing**
Ensure `rich` is installed (`pip install rich`). Use `--no-tui` to fall back to plain logging.

## Project Structure

```
src/
├── clients/
│   ├── bankr.py          # Bankr wallet/transaction API
│   ├── coordinator.py     # Challenge coordinator API
│   └── llm.py            # Bankr LLM Gateway client
├── solver/
│   ├── extractor.py       # Per-company LLM data extraction
│   ├── solver.py          # Main solve pipeline orchestrator
│   ├── prompts.py         # All LLM system prompts
│   ├── models.py          # Pydantic response models
│   └── validator.py       # Post-LLM programmatic validation
├── mining/
│   ├── loop.py            # Main mining loop
│   └── receipt.py         # Transaction receipt posting
├── ui/
│   └── display.py         # Rich TUI display
├── claiming/              # Epoch reward claiming
├── staking/               # BOTCOIN staking
├── auth/                  # Token management
├── config.py              # Environment config
├── credits.py             # LLM credit management
├── setup.py               # First-run setup wizard
├── main.py                # CLI entry point
├── errors.py              # Error classification
├── logger.py              # Logging setup
├── retry.py               # Retry with backoff
├── shutdown.py            # Graceful shutdown
└── types.py               # Pydantic API models
```

## License

MIT — see [LICENSE](LICENSE).
