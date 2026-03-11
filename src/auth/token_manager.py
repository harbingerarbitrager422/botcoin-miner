"""Auth handshake, JWT cache, mutex, refresh jitter."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import time

from ..clients.coordinator import CoordinatorClient, CoordinatorAPIError
from ..clients.bankr import BankrClient, BankrAPIError
from ..errors import Action, ClassifiedError, StopError
from ..retry import with_retry

logger = logging.getLogger(__name__)


class TokenManager:
    def __init__(self, miner: str, coordinator: CoordinatorClient, bankr: BankrClient):
        self.miner = miner
        self.coordinator = coordinator
        self.bankr = bankr
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _decode_jwt_exp(self, token: str) -> float:
        try:
            payload_b64 = token.split(".")[1]
            # Add padding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return float(payload.get("exp", time.time() + 600))
        except Exception:
            return time.time() + 600

    def _needs_refresh(self) -> bool:
        if not self._token:
            return True
        jitter = random.uniform(30, 90)
        return time.time() >= (self._expires_at - 60 - jitter)

    async def get_token(self) -> str:
        if not self._needs_refresh() and self._token:
            return self._token
        async with self._lock:
            # Double-check after acquiring lock
            if not self._needs_refresh() and self._token:
                return self._token
            await self._auth_handshake()
            assert self._token
            return self._token

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0

    async def _auth_handshake(self) -> None:
        logger.info("Starting auth handshake...")

        # Step 1: Get nonce
        nonce_resp = await self._get_nonce_with_retry()
        message = nonce_resp.message
        logger.debug(f"Got nonce message ({len(message)} chars)")

        # Step 2: Sign via Bankr
        sign_resp = await self.bankr.sign_message(message)
        signature = sign_resp.signature
        logger.debug("Message signed")

        # Step 3: Verify and get token
        token = await self._verify_with_retry(message, signature)
        self._token = token
        self._expires_at = self._decode_jwt_exp(token)
        logger.info(f"Auth complete, token expires at {self._expires_at:.0f}")

    async def _get_nonce_with_retry(self):
        def classify(exc: Exception) -> ClassifiedError:
            if isinstance(exc, CoordinatorAPIError):
                return exc.classified
            return ClassifiedError(Action.RETRY, str(exc))

        return await with_retry(
            lambda: self.coordinator.get_nonce(self.miner),
            classify,
            max_attempts=3,
        )

    async def _verify_with_retry(self, message: str, signature: str) -> str:
        verify_attempts = 0
        max_verify_attempts = 3

        while verify_attempts < max_verify_attempts:
            try:
                resp = await self.coordinator.verify(self.miner, message, signature)
                return resp.token
            except CoordinatorAPIError as e:
                verify_attempts += 1
                if e.status == 429:
                    if verify_attempts >= max_verify_attempts:
                        wait = random.uniform(60, 120)
                        logger.warning(f"Verify 429 after {max_verify_attempts} attempts, sleeping {wait:.0f}s then fresh nonce")
                        await asyncio.sleep(wait)
                        # Fresh nonce + re-sign
                        nonce_resp = await self.coordinator.get_nonce(self.miner)
                        sign_resp = await self.bankr.sign_message(nonce_resp.message)
                        resp = await self.coordinator.verify(self.miner, nonce_resp.message, sign_resp.signature)
                        return resp.token
                    wait = random.uniform(2, 5) * verify_attempts
                    logger.warning(f"Verify 429, retrying in {wait:.1f}s ({verify_attempts}/{max_verify_attempts})")
                    await asyncio.sleep(wait)
                elif e.status == 401:
                    # Fresh nonce + re-sign once
                    logger.warning("Verify 401, getting fresh nonce")
                    nonce_resp = await self.coordinator.get_nonce(self.miner)
                    sign_resp = await self.bankr.sign_message(nonce_resp.message)
                    resp = await self.coordinator.verify(self.miner, nonce_resp.message, sign_resp.signature)
                    return resp.token
                elif e.status == 403:
                    raise StopError(e.classified) from e
                else:
                    raise

        raise StopError(ClassifiedError(Action.STOP, "Verify failed after all attempts"))
