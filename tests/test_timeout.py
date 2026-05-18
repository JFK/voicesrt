"""Tests for explicit timeouts on external LLM calls.

Covers .claude/rules/async-first.md — "All external API calls must have
explicit timeouts" — verified for both providers:

- OpenAI: explicit httpx.Timeout on the AsyncOpenAI / openai-compatible client
- Gemini: asyncio.wait_for around to_thread via call_gemini_with_timeout
"""

import asyncio
import time

import httpx
import pytest

from src.services.utils import (
    GEMINI_TIMEOUT_SEC,
    OPENAI_CONNECT_TIMEOUT_SEC,
    OPENAI_TIMEOUT_SEC,
    call_gemini_with_timeout,
    create_openai_compatible_client,
)


class TestTimeoutConstants:
    def test_openai_timeout_matches_gemini(self):
        # Whisper / Gemini both process multi-minute audio; aligning timeouts
        # keeps the two providers operationally indistinguishable from a
        # user-perceived-hang perspective.
        assert OPENAI_TIMEOUT_SEC == GEMINI_TIMEOUT_SEC == 600.0

    def test_openai_connect_timeout_is_short(self):
        # Connect must fail fast; only the total budget is generous.
        assert OPENAI_CONNECT_TIMEOUT_SEC == 10.0


class TestCreateOpenAICompatibleClientTimeout:
    def test_openai_default_timeout(self):
        client = create_openai_compatible_client("openai", "sk-fake")
        assert isinstance(client.timeout, httpx.Timeout)
        assert client.timeout.read == OPENAI_TIMEOUT_SEC
        assert client.timeout.connect == OPENAI_CONNECT_TIMEOUT_SEC

    def test_ollama_default_timeout(self):
        client = create_openai_compatible_client("ollama", "http://localhost:11434")
        assert isinstance(client.timeout, httpx.Timeout)
        assert client.timeout.read == OPENAI_TIMEOUT_SEC
        assert client.timeout.connect == OPENAI_CONNECT_TIMEOUT_SEC

    def test_custom_timeout_override(self):
        custom = httpx.Timeout(5.0, connect=1.0)
        client = create_openai_compatible_client("openai", "sk-fake", timeout=custom)
        assert isinstance(client.timeout, httpx.Timeout)
        assert client.timeout.read == 5.0
        assert client.timeout.connect == 1.0


class TestCallGeminiWithTimeout:
    @pytest.mark.asyncio
    async def test_returns_value_when_fn_completes(self):
        def quick():
            return "ok"

        result = await call_gemini_with_timeout(quick)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_forwards_args_and_kwargs(self):
        def add(a, b, *, c=0):
            return a + b + c

        result = await call_gemini_with_timeout(add, 1, 2, c=3)
        assert result == 6

    @pytest.mark.asyncio
    async def test_raises_timeout_when_fn_hangs(self):
        def hang():
            # Real Gemini hang would be much longer; use a tiny budget so the
            # test stays under a second. Sleep slightly longer than timeout to
            # give wait_for a chance to fire.
            time.sleep(0.5)
            return "should not reach"

        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await call_gemini_with_timeout(hang, timeout=0.05)

    @pytest.mark.asyncio
    async def test_propagates_fn_exceptions(self):
        def boom():
            raise RuntimeError("from gemini")

        with pytest.raises(RuntimeError, match="from gemini"):
            await call_gemini_with_timeout(boom)

    @pytest.mark.asyncio
    async def test_default_timeout_is_gemini_timeout_sec(self):
        # Inspect the helper's default timeout without actually waiting it out.
        import inspect

        sig = inspect.signature(call_gemini_with_timeout)
        assert sig.parameters["timeout"].default == GEMINI_TIMEOUT_SEC
