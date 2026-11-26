import asyncio
import contextlib

import anyio

from app.agent.tools import restaurants
from app.config import Settings


class FakeMcpClient:
    """Like the real MCP client: holds an anyio task group, so it must be exited in the task that entered it."""

    def __init__(self, transport):
        self._tg = None

    async def __aenter__(self):
        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._tg.__aexit__(*exc)

    async def list_tools(self):
        return "tools"


async def test_session_opened_in_tool_task_closes_from_turn_task(monkeypatch):
    monkeypatch.setattr(restaurants, "Client", FakeMcpClient)
    monkeypatch.setattr(restaurants, "streamable_http_client", lambda url, http_client: None)
    monkeypatch.setattr(restaurants, "_http_client", lambda settings: contextlib.AsyncExitStack())

    session = restaurants.RestaurantSession(Settings(_env_file=None))

    async def tool_call():  # the runner runs each tool in its own task via asyncio.gather
        return await (await session.client()).list_tools()

    assert await asyncio.gather(tool_call(), tool_call()) == ["tools", "tools"]
    await session.aclose()  # used to raise "Attempted to exit cancel scope in a different task"


async def test_close_without_connecting_is_a_noop():
    await restaurants.RestaurantSession(Settings(_env_file=None)).aclose()
