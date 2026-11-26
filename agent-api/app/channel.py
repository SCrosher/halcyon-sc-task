"""Output channel for one agent turn.

Every assistant message is persisted (so non-streaming clients see it on their next
poll) and, when a streaming client is attached, pushed as an SSE event. A watchdog
posts a short holding message whenever nothing has gone out to the member for
``holding_message_after_seconds``, so the member never waits more than ~12 seconds.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .agent.progress import Activity, HoldingMessages
from .schemas import MessageOut
from .store import Message, Store

log = logging.getLogger(__name__)

TURN_COMPLETED = "turn.completed"


class TurnChannel:
    def __init__(self, store: Store, conversation_id: str, *, streaming: bool, holding_after: float):
        self.store = store
        self.conversation_id = conversation_id
        self.streaming = streaming
        self.events: asyncio.Queue[tuple[str, dict[str, Any]]] | None = asyncio.Queue() if streaming else None
        self.activity: Activity = "starting"
        self._holding_after = holding_after
        self._holding = HoldingMessages()
        self._last_sent = time.monotonic()
        self._post_lock = asyncio.Lock()
        self._watchdog: asyncio.Task | None = None
        self._closed = False

    def emit(self, event: str, data: dict[str, Any]) -> None:
        if self.events is not None:
            self.events.put_nowait((event, data))

    def _mark_sent(self) -> None:
        self._last_sent = time.monotonic()

    async def post(self, text: str, kind: str = "message") -> Message | None:
        """Persist an assistant message and push it to any streaming client.

        ``kind="status"`` marks progress lines, which are left out of later conversations' context.
        """
        text = text.strip()
        if not text:
            return None
        async with self._post_lock:
            message = await self.store.add_message(self.conversation_id, "assistant", text, kind=kind)
            self._mark_sent()
            self.emit("message.created", MessageOut.of(message).model_dump())
            return message

    def delta(self, text: str) -> None:
        self.emit("reply.delta", {"text": text})
        if self.streaming:
            self._mark_sent()  # a streaming member is seeing output, so no holding message is needed

    def reset_reply(self) -> None:
        """Tell a streaming client to discard the unposted draft (the model call is being re-issued)."""
        self.emit("reply.reset", {})

    def start(self) -> None:
        """Start the holding-message watchdog."""
        self._mark_sent()
        self._watchdog = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        while not self._closed:
            remaining = self._holding_after - (time.monotonic() - self._last_sent)
            if remaining > 0:
                await asyncio.sleep(min(remaining, 0.25))
                continue
            if self._closed:
                return
            try:
                await self.post(self._holding.next(self.activity), kind="status")
            except Exception:  # a failed holding message must never break the turn
                log.exception("Failed to post holding message")
                self._mark_sent()

    async def close(self, status: str) -> None:
        # Let the watchdog notice the flag (within 0.25s) rather than cancelling it mid-write.
        self._closed = True
        if self._watchdog is not None:
            await self._watchdog
        self.emit(TURN_COMPLETED, {"status": status})
