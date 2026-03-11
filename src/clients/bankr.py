"""All Bankr API calls (typed)."""

from __future__ import annotations

import logging

import httpx

from ..errors import classify_bankr_error
from ..types import BankrSubmitResponse, BankrSignResponse, OnChainTransaction

logger = logging.getLogger(__name__)

BANKR_BASE = "https://api.bankr.bot"


class BankrAPIError(Exception):
    def __init__(self, status: int, body: dict | str):
        self.status = status
        self.body = body
        self.classified = classify_bankr_error(status, body)
        super().__init__(self.classified.message)


class BankrClient:
    def __init__(self, api_key: str, timeout: float = 60.0):
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _check(self, resp: httpx.Response) -> None:
        if resp.status_code == 200:
            return
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise BankrAPIError(resp.status_code, body)

    async def get_me(self) -> dict:
        resp = await self.client.get(f"{BANKR_BASE}/agent/me")
        await self._check(resp)
        return resp.json()

    async def sign_message(self, message: str) -> BankrSignResponse:
        resp = await self.client.post(
            f"{BANKR_BASE}/agent/sign",
            json={"signatureType": "personal_sign", "message": message},
        )
        await self._check(resp)
        return BankrSignResponse.model_validate(resp.json())

    async def get_balances(self) -> dict:
        """Get wallet balances. Returns the full response dict."""
        resp = await self.client.get(f"{BANKR_BASE}/agent/balances")
        await self._check(resp)
        return resp.json()

    async def submit_transaction(
        self, tx: OnChainTransaction, description: str = "BOTCOIN transaction",
    ) -> BankrSubmitResponse:
        resp = await self.client.post(
            f"{BANKR_BASE}/agent/submit",
            json={
                "transaction": {
                    "to": tx.to,
                    "chainId": tx.chainId,
                    "value": tx.value,
                    "data": tx.data,
                },
                "description": description,
                "waitForConfirmation": True,
            },
        )
        await self._check(resp)
        return BankrSubmitResponse.model_validate(resp.json())
