"""Decode BOTCOIN reward amount from on-chain claim transaction receipt."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_RPC = "https://mainnet.base.org"
BOTCOIN_TOKEN = "0xA601877977340862Ca67f816eb079958E5bd0BA3".lower()
# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


async def get_claim_reward(tx_hash: str, recipient: str | None = None) -> float | None:
    """Fetch tx receipt and return BOTCOIN amount transferred to recipient.

    Returns None if decoding fails (non-critical — just means reward won't be logged).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                BASE_RPC,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_getTransactionReceipt",
                    "params": [tx_hash],
                    "id": 1,
                },
            )
            data = resp.json()
            receipt = data.get("result")
            if not receipt or receipt.get("status") != "0x1":
                return None

            recipient_lower = recipient.lower() if recipient else None
            total = 0.0
            for log in receipt.get("logs", []):
                topics = log.get("topics", [])
                if (
                    len(topics) >= 3
                    and topics[0] == TRANSFER_TOPIC
                    and log.get("address", "").lower() == BOTCOIN_TOKEN
                ):
                    to_addr = "0x" + topics[2][-40:]
                    if recipient_lower and to_addr.lower() != recipient_lower:
                        continue
                    amount_raw = int(log["data"], 16)
                    total += amount_raw / 1e18

            return total if total > 0 else None
    except Exception as e:
        logger.debug(f"Failed to decode claim reward from {tx_hash}: {e}")
        return None
