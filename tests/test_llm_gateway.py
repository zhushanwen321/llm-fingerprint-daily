"""LLMGateway 单元测试 — 覆盖重试、超时、并发控制和正常路径"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from src.config.schema import AppConfig, EvaluationConfig, ProviderConfig
from src.engine.llm_gateway import LLMGateway, RawResponse


def _make_config(
    max_concurrent: int = 5,
    max_retries: int = 5,
    retry_intervals: list[float] | None = None,
    timeout: int = 60,
    provider_concurrency: int = 2,
) -> AppConfig:
    """构造测试用 AppConfig"""
    return AppConfig(
        providers={
            "test-provider": ProviderConfig(
                base_url="https://api.example.com",
                api_key="test-key",
                concurrency=provider_concurrency,
            ),
        },
        evaluation=EvaluationConfig(
            schedule=[],
            max_llm_concurrent=max_concurrent,
            max_retries=max_retries,
            retry_intervals=retry_intervals or [0.01, 0.02],
            timeout=timeout,
        ),
    )


class MockResponse:
    """模拟 httpx.Response"""

    def __init__(
        self,
        text: str = "ok",
        status_code: int = 200,
        json_data: dict | None = None,
    ):
        self._text = text
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is not None:
            return self._json
        return {
            "content": [{"type": "text", "text": self._text}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            # httpx.HTTPStatusError 需要 Request/Response，此处仅模拟失败场景
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("POST", "https://test"),
                response=httpx.Response(self.status_code),
            )


class TestCallSuccess:
    """正常调用路径"""

    @pytest.mark.asyncio
    async def test_basic_call(self):
        config = _make_config()
        gateway = LLMGateway(config)

        async def mock_post(*_, **__):
            return MockResponse(text="hello world")

        gateway._client = type("Client", (), {"post": mock_post})()

        result = await gateway.call(
            "test-provider", "model-a", [{"role": "user", "content": "hi"}]
        )
        assert isinstance(result, RawResponse)
        assert result.text == "hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.stop_reason == "end_turn"
        assert result.latency_ms >= 0


class TestRetryOnTimeout:
    """超时重试 — 前 N 次超时，第 N+1 次成功"""

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        config = _make_config(max_retries=5, retry_intervals=[0.01])
        gateway = LLMGateway(config)

        call_count = 0

        async def mock_post(*_, **__):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.TimeoutException("timeout")
            return MockResponse(text="recovered")

        gateway._client = type("Client", (), {"post": mock_post})()

        result = await gateway.call(
            "test-provider", "model-a", [{"role": "user", "content": "hi"}]
        )
        assert call_count == 3
        assert result.text == "recovered"

    @pytest.mark.asyncio
    async def test_exhaust_retries_raises(self):
        config = _make_config(max_retries=2, retry_intervals=[0.01])
        gateway = LLMGateway(config)

        async def mock_post(*_, **__):
            raise httpx.TimeoutException("timeout")

        gateway._client = type("Client", (), {"post": mock_post})()

        with pytest.raises(httpx.TimeoutException):
            await gateway.call(
                "test-provider", "model-a", [{"role": "user", "content": "hi"}]
            )


class TestRetryOnHttpError:
    """HTTP 错误状态码重试"""

    @pytest.mark.asyncio
    async def test_retry_on_529(self):
        config = _make_config(max_retries=3, retry_intervals=[0.01])
        gateway = LLMGateway(config)

        call_count = 0

        async def mock_post(*_, **__):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return MockResponse(status_code=529)
            return MockResponse(text="ok")

        gateway._client = type("Client", (), {"post": mock_post})()

        result = await gateway.call(
            "test-provider", "model-a", [{"role": "user", "content": "hi"}]
        )
        assert call_count == 2
        assert result.text == "ok"


class TestConcurrencyControl:
    """全局 Semaphore 限流验证"""

    @pytest.mark.asyncio
    async def test_global_semaphore_throttling(self):
        # 全局并发限制为 1，确保串行执行
        config = _make_config(max_concurrent=1, provider_concurrency=1)
        gateway = LLMGateway(config)

        timestamps: list[float] = []

        async def slow_post(*_, **__):
            timestamps.append(time.monotonic())
            await asyncio.sleep(0.05)
            return MockResponse(text="done")

        gateway._client = type("Client", (), {"post": slow_post})()

        # 并发发起 3 个请求，全局限制为 1，应该串行
        tasks = [
            gateway.call("test-provider", "m", [{"role": "user", "content": "hi"}])
            for _ in range(3)
        ]
        await asyncio.gather(*tasks)

        assert len(timestamps) == 3
        # 每个请求间隔 >= 50ms（串行），如果并行则间隔接近 0
        for i in range(1, len(timestamps)):
            assert timestamps[i] - timestamps[i - 1] >= 0.04


class TestRequestConstruction:
    """验证构造的 HTTP 请求参数"""

    @pytest.mark.asyncio
    async def test_request_url_and_headers(self):
        config = _make_config()
        gateway = LLMGateway(config)

        captured: dict = {}

        async def mock_post(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            captured["json"] = kwargs.get("json", {})
            return MockResponse()

        # staticmethod 避免 Python 描述符绑定 self
        gateway._client = type("Client", (), {"post": staticmethod(mock_post)})()

        await gateway.call(
            "test-provider",
            "model-a",
            [{"role": "user", "content": "hello"}],
        )

        assert captured["url"] == "https://api.example.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "test-key"
        assert captured["headers"]["anthropic-version"] == "2023-06-01"
        assert captured["json"]["model"] == "model-a"
        assert captured["json"]["messages"] == [{"role": "user", "content": "hello"}]
        assert captured["json"]["temperature"] == 0
