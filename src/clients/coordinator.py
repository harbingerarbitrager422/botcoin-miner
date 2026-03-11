"""All coordinator API calls (typed)."""

from __future__ import annotations

import logging

import httpx

from ..errors import classify_coordinator_error, ClassifiedError, Action
from ..types import (
    Challenge, SubmitResponse, EpochInfo, NonceResponse, VerifyResponse,
    TransactionWrapper, CreditsResponse, BonusStatusResponse, StakeInfoResponse,
)

logger = logging.getLogger(__name__)


class CoordinatorAPIError(Exception):
    def __init__(self, endpoint: str, status: int, body: dict | str):
        self.endpoint = endpoint
        self.status = status
        self.body = body
        self.classified = classify_coordinator_error(endpoint, status, body)
        super().__init__(self.classified.message)


class CoordinatorClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "BotcoinMiner/1.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, token: str | None = None) -> dict:
        h: dict[str, str] = {}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    async def _check(self, endpoint: str, resp: httpx.Response) -> None:
        if resp.status_code == 200:
            return
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise CoordinatorAPIError(endpoint, resp.status_code, body)

    # --- Auth ---

    async def get_nonce(self, miner: str) -> NonceResponse:
        resp = await self.client.post(
            f"{self.base_url}/v1/auth/nonce",
            json={"miner": miner},
        )
        await self._check("auth/nonce", resp)
        return NonceResponse.model_validate(resp.json())

    async def verify(self, miner: str, message: str, signature: str) -> VerifyResponse:
        resp = await self.client.post(
            f"{self.base_url}/v1/auth/verify",
            json={"miner": miner, "message": message, "signature": signature},
        )
        await self._check("auth/verify", resp)
        return VerifyResponse.model_validate(resp.json())

    # --- Challenge ---

    async def get_challenge(self, miner: str, nonce: str, token: str) -> Challenge:
        resp = await self.client.get(
            f"{self.base_url}/v1/challenge",
            params={"miner": miner, "nonce": nonce},
            headers=self._headers(token),
        )
        await self._check("challenge", resp)
        return Challenge.model_validate(resp.json())

    async def submit(
        self, miner: str, challenge_id: str, artifact: str, nonce: str,
        token: str, pool: bool = False,
    ) -> SubmitResponse:
        body: dict = {
            "miner": miner,
            "challengeId": challenge_id,
            "artifact": artifact,
            "nonce": nonce,
        }
        if pool:
            body["pool"] = True
        resp = await self.client.post(
            f"{self.base_url}/v1/submit",
            json=body,
            headers=self._headers(token),
        )
        await self._check("submit", resp)
        return SubmitResponse.model_validate(resp.json())

    # --- Epoch / Credits ---

    async def get_epoch(self) -> EpochInfo:
        resp = await self.client.get(f"{self.base_url}/v1/epoch")
        await self._check("epoch", resp)
        return EpochInfo.model_validate(resp.json())

    async def get_credits(self, miner: str) -> dict:
        resp = await self.client.get(
            f"{self.base_url}/v1/credits",
            params={"miner": miner},
        )
        await self._check("credits", resp)
        return resp.json()

    async def get_token_info(self) -> dict:
        resp = await self.client.get(f"{self.base_url}/v1/token")
        await self._check("token", resp)
        return resp.json()

    # --- Claim ---

    async def get_claim_calldata(self, epochs: str, target: str | None = None) -> TransactionWrapper:
        params: dict = {"epochs": epochs}
        if target:
            params["target"] = target
        resp = await self.client.get(
            f"{self.base_url}/v1/claim-calldata",
            params=params,
        )
        await self._check("claim-calldata", resp)
        return TransactionWrapper.model_validate(resp.json())

    async def get_legacy_claim_calldata(self, epochs: str) -> TransactionWrapper:
        resp = await self.client.get(
            f"{self.base_url}/v1/claim-calldata-v1",
            params={"epochs": epochs},
        )
        await self._check("claim-calldata-v1", resp)
        return TransactionWrapper.model_validate(resp.json())

    # --- Bonus ---

    async def get_bonus_status(self, epochs: str) -> BonusStatusResponse:
        resp = await self.client.get(
            f"{self.base_url}/v1/bonus/status",
            params={"epochs": epochs},
        )
        await self._check("bonus/status", resp)
        return BonusStatusResponse.model_validate(resp.json())

    async def get_bonus_claim_calldata(self, epochs: str, target: str | None = None) -> TransactionWrapper:
        params: dict = {"epochs": epochs}
        if target:
            params["target"] = target
        resp = await self.client.get(
            f"{self.base_url}/v1/bonus/claim-calldata",
            params=params,
        )
        await self._check("bonus/claim-calldata", resp)
        return TransactionWrapper.model_validate(resp.json())

    # --- Staking ---

    async def get_stake_info(self, miner: str) -> StakeInfoResponse:
        resp = await self.client.get(
            f"{self.base_url}/v1/stake-info",
            params={"miner": miner},
        )
        await self._check("stake-info", resp)
        return StakeInfoResponse.model_validate(resp.json())

    async def get_stake_approve_calldata(self, amount: str) -> TransactionWrapper:
        resp = await self.client.get(
            f"{self.base_url}/v1/stake-approve-calldata",
            params={"amount": amount},
        )
        await self._check("stake-approve-calldata", resp)
        return TransactionWrapper.model_validate(resp.json())

    async def get_stake_calldata(self, amount: str) -> TransactionWrapper:
        resp = await self.client.get(
            f"{self.base_url}/v1/stake-calldata",
            params={"amount": amount},
        )
        await self._check("stake-calldata", resp)
        return TransactionWrapper.model_validate(resp.json())

    async def get_unstake_calldata(self) -> TransactionWrapper:
        resp = await self.client.get(f"{self.base_url}/v1/unstake-calldata")
        await self._check("unstake-calldata", resp)
        return TransactionWrapper.model_validate(resp.json())

    async def get_withdraw_calldata(self) -> TransactionWrapper:
        resp = await self.client.get(f"{self.base_url}/v1/withdraw-calldata")
        await self._check("withdraw-calldata", resp)
        return TransactionWrapper.model_validate(resp.json())
