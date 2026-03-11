"""Bankr LLM Gateway client — async httpx, structured JSON output."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import re as _re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BANKR_LLM_BASE = "https://llm.bankr.bot"


class InsufficientCreditsError(Exception):
    """Raised when LLM gateway returns 402 / payment required."""


class LLMClient:
    def __init__(
        self,
        small_model: str,
        large_model: str,
        temperature: float = 0.0,
        api_key: str = "",
        base_url: str = BANKR_LLM_BASE,
    ):
        self.small_model = small_model
        self.large_model = large_model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        if not self.api_key:
            raise ValueError("Bankr API key required")

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers={
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            },
            limits=httpx.Limits(
                max_connections=40,
                max_keepalive_connections=35,
            ),
        )
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def close(self) -> None:
        await self._client.aclose()

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(30)
        return self._semaphore

    def _pydantic_to_json_schema(self, model_class: Any) -> dict:
        if hasattr(model_class, "model_json_schema"):
            schema = copy.deepcopy(model_class.model_json_schema())
        else:
            schema = copy.deepcopy(model_class.schema())

        defs = schema.pop("$defs", schema.pop("definitions", {}))

        def resolve_refs(obj):
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref_path = obj["$ref"]
                    ref_name = ref_path.split("/")[-1]
                    if ref_name in defs:
                        resolved = copy.deepcopy(defs[ref_name])
                        resolve_refs(resolved)
                        obj.clear()
                        obj.update(resolved)
                        return
                for value in obj.values():
                    if isinstance(value, dict):
                        resolve_refs(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                resolve_refs(item)

        resolve_refs(schema)

        def fix_schema(obj):
            if isinstance(obj, dict):
                obj.pop("title", None)
                obj.pop("default", None)

                if obj.get("type") == "object":
                    if "additionalProperties" not in obj:
                        obj["additionalProperties"] = False
                    if "properties" in obj:
                        obj["required"] = list(obj["properties"].keys())

                if "anyOf" in obj and len(obj["anyOf"]) == 2:
                    types = obj["anyOf"]
                    non_null = [t for t in types if t.get("type") != "null"]
                    has_null = any(t.get("type") == "null" for t in types)
                    if has_null and len(non_null) == 1:
                        obj.pop("anyOf")
                        obj.update(non_null[0])
                        obj["nullable"] = True

                for value in obj.values():
                    if isinstance(value, dict):
                        fix_schema(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                fix_schema(item)

        fix_schema(schema)
        if "additionalProperties" not in schema:
            schema["additionalProperties"] = False

        return {
            "name": model_class.__name__.lower(),
            "strict": True,
            "schema": schema,
        }

    async def generate_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Any,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        timeout: int = 120,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> Optional[dict]:
        model = model or self.small_model
        json_schema = self._pydantic_to_json_schema(response_model)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        sem = self._get_semaphore()
        async with sem:
            for attempt in range(max_retries):
                try:
                    response = await self._call_gateway(
                        model, messages, json_schema, temperature, max_tokens, timeout,
                    )
                    if response is not None:
                        return response
                except InsufficientCreditsError:
                    raise
                except Exception as e:
                    logger.warning(f"LLM attempt {attempt + 1}/{max_retries} failed: {e}")

                if attempt < max_retries - 1:
                    base_delay = retry_delay * (2 ** attempt)
                    jitter = random.uniform(0, base_delay * 0.5)
                    await asyncio.sleep(base_delay + jitter)
                else:
                    logger.error("All LLM retry attempts failed")

        return None

    async def _call_gateway(
        self, model: str, messages: list, json_schema: dict,
        temperature: float, max_tokens: int, timeout: int,
    ) -> Optional[dict]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": json_schema,
            },
        }

        response = await self._client.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=timeout,
        )

        if response.status_code == 402:
            raise InsufficientCreditsError(
                f"Insufficient LLM credits: {response.text[:300]}"
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"LLM gateway {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason", "")
            if finish_reason == "length":
                logger.warning(
                    f"LLM response truncated (finish_reason=length), "
                    f"max_tokens={max_tokens}"
                )
            content = choice.get("message", {}).get("content", "")
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    fixed = _re.sub(r'([{,])\s*(\w+)\s*:', r'\1"\2":', content)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass
                    result = {}
                    for m in _re.finditer(
                        r'["\']?(\w+)["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                        content,
                    ):
                        result[m.group(1)] = m.group(2)
                    if result:
                        return result
                    raise

        return None

    async def check_health(self) -> dict:
        resp = await self._client.get(f"{self.base_url}/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    async def list_models(self) -> list[dict]:
        """Fetch available models from the gateway. Returns list of model objects."""
        resp = await self._client.get(f"{self.base_url}/v1/models", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # OpenAI-compatible format: {"data": [{"id": "...", ...}, ...]}
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    async def get_usage(self, days: int = 1) -> dict:
        resp = await self._client.get(
            f"{self.base_url}/v1/usage",
            params={"days": days},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
