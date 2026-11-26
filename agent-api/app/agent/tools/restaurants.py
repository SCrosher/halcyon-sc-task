"""Restaurant tools discovered from the mock restaurant MCP server."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from contextlib import AsyncExitStack
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from ...config import Settings
from ..progress import Activity
from .base import Tool, ToolFailure, TurnContext

log = logging.getLogger(__name__)

# Filled in by the server from the authenticated member; never chosen by the model.
INJECTED_ARGS = ("member_id", "member_name")
ACTIVITY: dict[str, Activity] = {
    "search_restaurants": "search",
    "get_restaurant": "search",
    "check_availability": "availability",
    "create_booking": "booking",
    "cancel_booking": "booking",
    "list_bookings": "bookings",
}
LIST_TTL_SECONDS = 600
CLOSE_TIMEOUT_SECONDS = 5.0


def _http_client(settings: Settings) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(headers=settings.mock_services_headers, timeout=httpx2.Timeout(30.0, read=60.0))


def _mcp_url(settings: Settings) -> str:
    return settings.mock_services_url.rstrip("/") + "/mcp"


def _model_schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(input_schema)
    for name in INJECTED_ARGS:
        schema.get("properties", {}).pop(name, None)
    schema["required"] = [r for r in schema.get("required", []) if r not in INJECTED_ARGS]
    return schema


class RestaurantSession:
    """Opens one MCP connection lazily, on the first restaurant tool call of a turn.

    The MCP client holds anyio cancel scopes, which must be entered and exited in the same
    task. Tool calls run in their own tasks (``asyncio.gather``) and the session is closed
    from the turn's task, so the connection lives in a dedicated task owned by this session.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Client | None = None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future[Client] | None = None
        self._closing = asyncio.Event()
        self._lock = asyncio.Lock()

    async def _serve(self, ready: asyncio.Future[Client]) -> None:
        try:
            async with AsyncExitStack() as stack:
                http = await stack.enter_async_context(_http_client(self._settings))
                transport = streamable_http_client(_mcp_url(self._settings), http_client=http)
                client = await stack.enter_async_context(Client(transport))
                ready.set_result(client)
                await self._closing.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError("MCP connection cancelled"))
            elif not isinstance(exc, Exception):
                raise
            else:
                log.warning("Restaurant MCP connection ended with an error", exc_info=True)

    async def client(self) -> Client:
        async with self._lock:
            if self._client is None:
                if self._task is None:
                    self._ready = asyncio.get_running_loop().create_future()
                    self._task = asyncio.create_task(self._serve(self._ready))
                # A failed connect leaves _task set, so later calls in this turn fail fast.
                self._client = await asyncio.shield(self._ready)
            return self._client

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            result = await (await self.client()).call_tool(name, arguments)
        except Exception as exc:  # transport / protocol failures
            raise ToolFailure(f"Restaurant service unavailable ({exc.__class__.__name__}).") from exc
        text = "\n".join(getattr(c, "text", "") for c in result.content).strip()
        if result.is_error:
            raise ToolFailure(text or "Restaurant service returned an error.")
        if result.structured_content is not None:
            return json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))
        return text

    async def aclose(self) -> None:
        if self._task is None:
            return
        self._closing.set()
        try:
            # A hung MCP shutdown must not hold the turn open; wait_for cancels the task on timeout.
            await asyncio.wait_for(self._task, CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("Restaurant MCP connection did not close within %ss", CLOSE_TIMEOUT_SECONDS)


class RestaurantCatalog:
    """Caches the MCP tool list so turns don't pay for a listing round-trip."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._definitions: list[Any] = []
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _definitions_cached(self) -> list[Any]:
        async with self._lock:
            if not self._definitions or time.monotonic() - self._fetched_at > LIST_TTL_SECONDS:
                async with (
                    _http_client(self._settings) as http,
                    Client(streamable_http_client(_mcp_url(self._settings), http_client=http)) as client,
                ):
                    listed = await client.list_tools()
                self._definitions = sorted(listed.tools, key=lambda t: t.name)
                self._fetched_at = time.monotonic()
            return self._definitions

    async def tools(self, session: RestaurantSession) -> list[Tool]:
        try:
            definitions = await self._definitions_cached()
        except Exception:
            log.exception("Could not list restaurant MCP tools; continuing without them")
            return []
        return [self._tool(d, session) for d in definitions]

    @staticmethod
    def _tool(definition: Any, session: RestaurantSession) -> Tool:
        name = definition.name
        wants = set(definition.input_schema.get("properties", {})) & set(INJECTED_ARGS)

        async def handler(args: dict[str, Any], ctx: TurnContext) -> str:
            injected = {"member_id": ctx.member.id, "member_name": ctx.member.name}
            return await session.call(name, {**args, **{k: injected[k] for k in wants}})

        return Tool(
            name=name,
            description=definition.description or name,
            parameters=_model_schema(definition.input_schema),
            source="restaurants",
            activity=ACTIVITY.get(name, "search"),
            handler=handler,
        )
