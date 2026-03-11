"""Pydantic models for all API responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OnChainTransaction(BaseModel):
    to: str
    chainId: int
    value: str
    data: str


class Challenge(BaseModel):
    epochId: int
    doc: str
    questions: list[str]
    constraints: list[str]
    companies: list[str]
    challengeId: str
    creditsPerSolve: int
    solveInstructions: str | None = None
    proposal: str | None = None


class SubmitResponse(BaseModel):
    pass_: bool = Field(alias="pass")
    receipt: dict | None = None
    signature: str | None = None
    transaction: OnChainTransaction | None = None
    failedConstraintIndices: list[int] | None = None

    model_config = {"populate_by_name": True}


class EpochInfo(BaseModel):
    epochId: int
    prevEpochId: int | None = None
    nextEpochStartTimestamp: int
    epochDurationSeconds: int


class BankrSubmitResponse(BaseModel):
    success: bool
    transactionHash: str | None = None
    status: str | None = None
    blockNumber: str | None = None
    gasUsed: str | None = None


class NonceResponse(BaseModel):
    message: str


class VerifyResponse(BaseModel):
    token: str


class BankrMeResponse(BaseModel):
    address: str | None = None
    wallets: list[dict] | None = None


class BankrSignResponse(BaseModel):
    signature: str


class CreditsResponse(BaseModel):
    credits: list[dict] | None = None


class TransactionWrapper(BaseModel):
    transaction: OnChainTransaction


class BonusStatusResponse(BaseModel):
    enabled: bool
    epochId: str | None = None
    isBonusEpoch: bool | None = None
    claimsOpen: bool | None = None
    reward: str | None = None
    rewardRaw: str | None = None


class StakeInfoResponse(BaseModel):
    staked: str | None = None
    stakedFormatted: str | None = None
    unstakePending: bool | None = None
    cooldownEnd: int | None = None
