"""LLM Gateway — 系统唯一的 LLM API 调用出口。

使用 Semaphore + rate limiter 双重控制：
  全局 Semaphore: 限制系统整体并发数
  Provider Semaphore: 限制单个 provider 的并发数
  Provider Rate Limiter: 限制单个 provider 的请求速率（RPM）

并发语义：
  Semaphore 在实际 HTTP 请求期间持有（包括 streaming），
  重试等待期间释放 Semaphore，避免浪费并发槽位。
"""

from __future__ import annotations

import asyncio
import logging
import random
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


class _RateLimiter:
    """滑动窗口速率限制器 — 控制单位时间内的请求数（RPM）"""

    def __init__(self, max_rpm: int) -> None:
        self._max_rpm = max_rpm
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """等待直到可以发送下一个请求（不超过 RPM 限制）"""
        while True:
            async with self._lock:
                now = time.monotonic()
                # 清理 60 秒前的记录
                cutoff = now - 60.0
                self._timestamps = [t for t in self._timestamps if t > cutoff]
                if len(self._timestamps) < self._max_rpm:
                    self._timestamps.append(now)
                    return
                # 计算需要等待的时间
                oldest_in_window = self._timestamps[0]
                wait_time = max(0.01, oldest_in_window + 60.0 - now + 0.1)
            # 在 lock 外等待，允许其他协程推进
            await asyncio.sleep(wait_time)


class LLMGateway:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._global_sem = asyncio.Semaphore(config.evaluation.max_llm_concurrent)
        # 每个 provider 独立的信号量
        self._provider_sems: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(p.concurrency)
            for name, p in config.providers.items()
        }
        # 每个 provider 独立的速率限制器
        self._provider_rate_limiters: dict[str, _RateLimiter] = {
            name: _RateLimiter(p.rpm) for name, p in config.providers.items()
            if p.rpm > 0
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
        temperature: float = 0,
    ) -> RawResponse:
        """调用指定 provider 的 LLM，带重试和并发控制。

        并发控制流程：
          1. 等待 provider 级别的速率限制
          2. 获取 global sem → provider sem
          3. 发送请求
          4. 如果失败，释放所有 semaphore 后 sleep，然后回到步骤 2 重试
        """
        provider_cfg = self._config.providers[provider]
        max_retries = self._config.evaluation.max_retries
        intervals = self._config.evaluation.retry_intervals
        # 请求完成后在 semaphore 内等待的间隔，确保两次请求间至少间隔这么久
        req_interval = getattr(provider_cfg, "request_interval", 0)

        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")

        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            # 速率限制（在 semaphore 外等待，不占用并发槽位）
            rate_limiter = self._provider_rate_limiters.get(provider)
            if rate_limiter:
                await rate_limiter.acquire()
            # 获取并发控制
            async with self._global_sem:
                async with self._provider_sems[provider]:
                    try:
                        result = await self._single_request(
                            provider_cfg, model, messages, max_tokens, temperature
                        )
                        # 成功后等待间隔再释放 semaphore
                        if req_interval > 0:
                            await asyncio.sleep(req_interval)
                        return result
                    except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                        last_exc = exc
                        # 失败后也等待间隔再释放 semaphore
                        if req_interval > 0:
                            await asyncio.sleep(req_interval)

            # 重试等待在 semaphore 外部执行，不占用并发槽位
            if attempt < max_retries:
                wait = self._config.get_retry_interval(intervals, attempt)
                jitter = random.uniform(0, wait * 0.5)
                total_wait = wait + jitter
                logger.warning(
                    "attempt %d failed (%s), retrying in %.1fs (jitter %.1fs)",
                    attempt, last_exc, wait, jitter,
                )
                await asyncio.sleep(total_wait)

        raise last_exc  # type: ignore[misc]

    async def _single_request(
        self,
        provider_cfg,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0,
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
            "temperature": temperature,
        }

        t0 = time.monotonic()
        resp = await client.post(url, headers=headers, json=payload)
        latency_ms = (time.monotonic() - t0) * 1000
        resp.raise_for_status()

        data = resp.json()
        content = data.get("content", [])
        first_item = content[0] if content else None
        text = first_item.get("text", "") if isinstance(first_item, dict) else ""
        usage = data.get("usage", {})
        return RawResponse(
            text=text,
            latency_ms=round(latency_ms, 2),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=data.get("stop_reason", ""),
        )
