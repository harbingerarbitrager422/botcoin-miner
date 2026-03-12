"""Query staking state directly from the BotcoinMiningV2 contract via eth_call."""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

BASE_RPC = "https://mainnet.base.org"
MINING_CONTRACT = "0xcf5f2d541eeb0fb4ca35f1973de5f2b02dfc3716"

# Function selectors (keccak256 of signature, first 4 bytes)
# stakedAmount(address) -> uint256
SEL_STAKED_AMOUNT = "0xf9931855"
# isEligible(address) -> bool
SEL_IS_ELIGIBLE = "0x66e305fd"
# withdrawableAt(address) -> uint256
SEL_WITHDRAWABLE_AT = "0x5a8c06ab"
# totalStaked() -> uint256
SEL_TOTAL_STAKED = "0x817b1cd2"
# tier1Balance() -> uint256
SEL_TIER1 = "0x86b3f61d"
# tier2Balance() -> uint256
SEL_TIER2 = "0x5ff9d5e2"
# tier3Balance() -> uint256
SEL_TIER3 = "0xd167adfb"

DECIMALS = 18


def _encode_address_call(selector: str, address: str) -> str:
    """Encode a call with a single address argument."""
    addr = address.lower().replace("0x", "").zfill(64)
    return selector + addr


async def _eth_call(
    client: httpx.AsyncClient, data: str, to: str = MINING_CONTRACT,
) -> str:
    """Make a raw eth_call and return the hex result (with retry for rate limits)."""
    import asyncio

    for attempt in range(3):
        resp = await client.post(
            BASE_RPC,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": to, "data": data}, "latest"],
                "id": 1,
            },
        )
        result = resp.json()
        if "error" in result:
            code = result["error"].get("code", 0)
            if code == -32016 and attempt < 2:  # rate limit
                await asyncio.sleep(1 + attempt)
                continue
            raise RuntimeError(f"eth_call error: {result['error']}")
        return result["result"]
    raise RuntimeError("eth_call: max retries exceeded")


def _decode_uint256(hex_result: str) -> int:
    """Decode a uint256 from hex."""
    if not hex_result or hex_result == "0x":
        return 0
    return int(hex_result, 16)


def _decode_bool(hex_result: str) -> bool:
    """Decode a bool from hex."""
    return _decode_uint256(hex_result) != 0


def _format_tokens(wei: int) -> str:
    """Format wei amount as human-readable token string."""
    whole = wei // (10 ** DECIMALS)
    frac = wei % (10 ** DECIMALS)
    if frac == 0:
        return f"{whole:,}"
    # Show up to 2 decimal places
    frac_str = f"{frac:0{DECIMALS}d}".rstrip("0")[:2]
    return f"{whole:,}.{frac_str}"


class StakeInfo:
    """On-chain staking state for a miner."""

    def __init__(
        self,
        staked_wei: int,
        is_eligible: bool,
        withdrawable_at: int,
        total_staked_wei: int,
        tier1_wei: int,
        tier2_wei: int,
        tier3_wei: int,
    ):
        self.staked_wei = staked_wei
        self.is_eligible = is_eligible
        self.withdrawable_at = withdrawable_at
        self.total_staked_wei = total_staked_wei
        self.tier1_wei = tier1_wei
        self.tier2_wei = tier2_wei
        self.tier3_wei = tier3_wei

    @property
    def staked_formatted(self) -> str:
        return _format_tokens(self.staked_wei)

    @property
    def total_staked_formatted(self) -> str:
        return _format_tokens(self.total_staked_wei)

    @property
    def unstake_pending(self) -> bool:
        return self.withdrawable_at > 0

    @property
    def cooldown_remaining(self) -> int | None:
        """Seconds until withdrawal is available, or None if no unstake pending."""
        if self.withdrawable_at == 0:
            return None
        remaining = self.withdrawable_at - int(time.time())
        return max(0, remaining)

    @property
    def tier(self) -> int:
        """Current staking tier (0 = none, 1-3 = tier)."""
        if self.staked_wei >= self.tier3_wei and self.tier3_wei > 0:
            return 3
        if self.staked_wei >= self.tier2_wei and self.tier2_wei > 0:
            return 2
        if self.staked_wei >= self.tier1_wei and self.tier1_wei > 0:
            return 1
        return 0

    def display(self) -> str:
        """Format stake info for CLI display."""
        lines = [
            f"Staked: {self.staked_formatted} BOTCOIN",
            f"Eligible: {'yes' if self.is_eligible else 'no'}",
            f"Tier: {self.tier}",
        ]
        if self.unstake_pending:
            cd = self.cooldown_remaining
            if cd is not None and cd > 0:
                h, m = cd // 3600, (cd % 3600) // 60
                lines.append(f"Unstake cooldown: {h}h {m}m remaining")
            else:
                lines.append("Unstake cooldown: ready to withdraw")
        lines.append(f"Total staked (network): {self.total_staked_formatted} BOTCOIN")
        tiers = []
        for i, wei in enumerate([self.tier1_wei, self.tier2_wei, self.tier3_wei], 1):
            tiers.append(f"T{i}={_format_tokens(wei)}")
        lines.append(f"Tier thresholds: {', '.join(tiers)}")
        return "\n".join(lines)


async def get_stake_info(miner: str) -> StakeInfo:
    """Fetch all staking state for a miner from the contract."""
    import asyncio

    async with httpx.AsyncClient(timeout=15) as client:
        # Run all reads in parallel
        staked_hex, eligible_hex, withdraw_hex, total_hex, t1_hex, t2_hex, t3_hex = (
            await asyncio.gather(
                _eth_call(client, _encode_address_call(SEL_STAKED_AMOUNT, miner)),
                _eth_call(client, _encode_address_call(SEL_IS_ELIGIBLE, miner)),
                _eth_call(client, _encode_address_call(SEL_WITHDRAWABLE_AT, miner)),
                _eth_call(client, SEL_TOTAL_STAKED),
                _eth_call(client, SEL_TIER1),
                _eth_call(client, SEL_TIER2),
                _eth_call(client, SEL_TIER3),
            )
        )

    return StakeInfo(
        staked_wei=_decode_uint256(staked_hex),
        is_eligible=_decode_bool(eligible_hex),
        withdrawable_at=_decode_uint256(withdraw_hex),
        total_staked_wei=_decode_uint256(total_hex),
        tier1_wei=_decode_uint256(t1_hex),
        tier2_wei=_decode_uint256(t2_hex),
        tier3_wei=_decode_uint256(t3_hex),
    )
