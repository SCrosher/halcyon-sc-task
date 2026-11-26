"""Thin wrapper over the Anthropic streaming Messages API for one model call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from ..config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
CLIENT_ONLY_FIELDS = {"parsed_output"}

OnText = Callable[[str], Awaitable[None]]
OnToolUse = Callable[[dict[str, Any]], Awaitable[None]]


class ToolInputParseError(Exception):
    """A streamed tool input was not valid JSON (possible with eager input streaming)."""


@dataclass
class ModelResponse:
    content: list[dict[str, Any]]  # assistant content blocks, ready to send back as message params
    stop_reason: str | None


def _block_param(block: Any) -> dict[str, Any]:
    data = block.to_dict(mode="json")
    return {k: v for k, v in data.items() if v is not None and k not in CLIENT_ONLY_FIELDS}


class ClaudeClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            max_retries=2,
            timeout=anthropic.Timeout(90.0, connect=10.0),
        )

    async def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text: OnText,
        on_tool_use: OnToolUse,
    ) -> ModelResponse:
        """Stream one model response, reporting text deltas and each completed tool_use block.

        Raises ``ToolInputParseError`` if a streamed tool input is not parseable JSON; the caller
        retries the call. Errors raised by the callbacks propagate unchanged.
        """
        kwargs: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": self.settings.max_output_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            "output_config": {"effort": self.settings.agent_effort},
            "cache_control": {"type": "ephemeral"},
        }
        if self.settings.anthropic_fallbacks == "default":
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        async with self._client.beta.messages.stream(**kwargs) as stream:
            events = stream.__aiter__()
            while True:
                # Only parsing inside the SDK counts as bad tool JSON, not errors from the callbacks.
                try:
                    event = await anext(events)
                except StopAsyncIteration:
                    break
                except ValueError as exc:
                    raise ToolInputParseError(str(exc)) from exc
                if event.type == "text":
                    await on_text(event.text)
                elif event.type == "content_block_stop" and event.content_block.type == "tool_use":
                    await on_tool_use(_block_param(event.content_block))
            try:
                message = await stream.get_final_message()
            except ValueError as exc:
                raise ToolInputParseError(str(exc)) from exc
        return ModelResponse(content=[_block_param(b) for b in message.content], stop_reason=message.stop_reason)

    async def aclose(self) -> None:
        await self._client.close()
