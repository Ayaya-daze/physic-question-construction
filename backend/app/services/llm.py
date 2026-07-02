"""LLM provider abstraction — supports Anthropic (Claude) and OpenAI-compatible backends.

Uses a Protocol-based design so new providers can be added without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """Standardized LLM response across providers."""

    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)  # {"input_tokens": N, "output_tokens": N}
    finish_reason: str = "stop"


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers. Implementations should accept system + user prompts."""

    supports_vision: bool = False

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse: ...

    async def complete_with_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse: ...

    async def complete_with_images(
        self,
        image_data: list[str],
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


class LLMNotConfiguredError(Exception):
    """Raised when LLM is requested but not configured."""

    pass


class NoopProvider:
    """No-op provider that raises an error — used when LLM_ENABLED=false."""

    supports_vision = False

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        raise LLMNotConfiguredError(
            "LLM is not enabled. Set LLM_ENABLED=true and configure LLM_API_KEY in .env"
        )

    async def complete_with_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        raise LLMNotConfiguredError(
            "LLM is not enabled. Set LLM_ENABLED=true and configure LLM_API_KEY in .env"
        )

    async def complete_with_images(
        self,
        image_data: list[str],
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        raise LLMNotConfiguredError(
            "LLM is not enabled. Set LLM_ENABLED=true and configure LLM_API_KEY in .env"
        )


class AnthropicProvider:
    """Claude API provider using the official anthropic SDK.  Supports vision."""

    supports_vision = True

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)

        messages = [{"role": "user", "content": prompt}]

        response = await client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )

        content_blocks = response.content
        text_parts: list[str] = []
        for block in content_blocks:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        return LLMResponse(
            content="\n".join(text_parts),
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            },
            finish_reason=response.stop_reason or "stop",
        )

    async def complete_with_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send an image + text prompt.  ``image_data`` is a base64 data URI."""
        return await self.complete_with_images(
            image_data=[image_data],
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def complete_with_images(
        self,
        image_data: list[str],
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send multiple rendered page images plus a text prompt."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)

        content_blocks = []
        for image in image_data:
            # Parse data URI: "data:image/png;base64,xxxx"
            if image.startswith("data:"):
                header, b64 = image.split(",", 1)
                media_type = header.split(":")[1].split(";")[0]
            else:
                media_type = "image/png"
                b64 = image
            content_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                }
            )
        content_blocks.append({"type": "text", "text": prompt})

        messages = [{
            "role": "user",
            "content": content_blocks,
        }]

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        response = await client.messages.create(**kwargs)

        text_parts: list[str] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        return LLMResponse(
            content="\n".join(text_parts),
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            },
            finish_reason=response.stop_reason or "stop",
        )


class OpenAICompatibleProvider:
    """OpenAI-compatible API provider using httpx.  Does NOT support vision by default."""

    supports_vision = False

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        import httpx

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.model),
            usage={
                "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
            },
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def complete_with_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send an image + text prompt via OpenAI-compatible vision API."""
        return await self.complete_with_images(
            image_data=[image_data],
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def complete_with_images(
        self,
        image_data: list[str],
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send multiple images + text prompt via OpenAI-compatible vision API."""
        import httpx

        content_blocks = []
        for image in image_data:
            # Parse data URI
            if image.startswith("data:"):
                header, b64 = image.split(",", 1)
                media_type = header.split(":")[1].split(";")[0]
            else:
                media_type = "image/png"
                b64 = image
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                }
            )
        content_blocks.append({"type": "text", "text": prompt})

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content_blocks})

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.model),
            usage={
                "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
            },
            finish_reason=choice.get("finish_reason", "stop"),
        )


# ── Factory ─────────────────────────────────────────────────────────────


def get_llm_provider() -> LLMProvider:
    """Factory function: returns the configured LLM provider or a NoopProvider."""
    from app.config import settings

    if not settings.LLM_ENABLED:
        return NoopProvider()

    if settings.LLM_PROVIDER == "anthropic":
        if not settings.LLM_API_KEY:
            raise LLMNotConfiguredError("LLM_API_KEY is not set.")
        return AnthropicProvider(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
        )
    elif settings.LLM_PROVIDER == "openai_compatible":
        if not settings.LLM_API_KEY:
            raise LLMNotConfiguredError("LLM_API_KEY is not set.")
        provider = OpenAICompatibleProvider(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL,
        )
        # Some OpenAI-compatible providers (e.g. vLLM with vision models, Ollama)
        # do support vision.  The user can opt in by setting LLM_VISION_ENABLED=true.
        if getattr(settings, 'LLM_VISION_ENABLED', False):
            provider.supports_vision = True
        return provider
    else:
        raise ValueError(f"Unknown LLM provider: {settings.LLM_PROVIDER}")
