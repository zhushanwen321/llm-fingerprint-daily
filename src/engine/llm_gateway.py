"""LLM Gateway — 系统唯一的 LLM API 调用出口。

使用两层 Semaphore 控制并发：
  全局 Semaphore: 限制系统整体并发数
  Provider Semaphore: 限制单个 provider 的并发数

调用 Anthropic Messages API 格式:
  POST {base_url}/v1/messages
  Headers: x-api-key, anthropic-version, content-type
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from src.config.schema import AppConfig

logger = logging.getLogger(__name__)


class RawResponse:
    """LLM 原始响应，不做任何后处理"""

    def __init__(
        self,
        text: str,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        stop_reason: str,
    ):
        self.text = text
        self.latency_ms = latency_ms
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.stop_reason = stop_reason


class LLMGateway:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._global_sem = asyncio.Semaphore(config.evaluation.max_llm_concurrent)
        # 每个 provider 独立的信号量
        self._provider_sems: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(p.concurrency)
            for name, p in config.providers.items()
        }
        # httpx.AsyncClient 由外部注入或延迟创建
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._config.evaluation.timeout)
        return self._client

    async def call(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        max_tokens: int = 1024,
    ) -> RawResponse:
        """调用指定 provider 的 LLM，带重试和并发控制"""
        provider_cfg = self._config.providers[provider]
        provider_sem = self._provider_sems[provider]

        async with self._global_sem:
            async with provider_sem:
                return await self._call_with_retry(
                    provider_cfg, model, messages, max_tokens
                )

    async def _call_with_retry(
        self,
        provider_cfg,
        model: str,
        messages: list[dict],
        max_tokens: int,
    ) -> RawResponse:
        max_retries = self._config.evaluation.max_retries
        intervals = self._config.evaluation.retry_intervals
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return await self._single_request(
                    provider_cfg, model, messages, max_tokens
                )
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = self._config.get_retry_interval(intervals, attempt)
                    logger.warning(
                        "attempt %d failed (%s), retrying in %.1fs",
                        attempt, exc, wait,
                    )
                    await asyncio.sleep(wait)

        raise last_exc  # type: ignore[misc]

    async def _single_request(
        self,
        provider_cfg,
        model: str,
        messages: list[dict],
        max_tokens: int,
    ) -> RawResponse:
        client = await self._ensure_client()
        url = f"{provider_cfg.base_url}/v1/messages"
        headers = {
            "x-api-key": provider_cfg.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **provider_cfg.default_headers,
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
        }

        t0 = time.monotonic()
        resp = await client.post(url, headers=headers, json=payload)
        latency_ms = (time.monotonic() - t0) * 1000
        resp.raise_for_status()

        data = resp.json()
        text = data["content"][0]["text"]
        usage = data.get("usage", {})
        return RawResponse(
            text=text,
            latency_ms=round(latency_ms, 2),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=data.get("stop_reason", ""),
        )
