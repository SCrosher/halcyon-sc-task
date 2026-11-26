"""Accepting member messages and scheduling agent turns.

Turns run in the background so POST can answer 202 straight away. Turns within one
conversation run one at a time, in order. The service runs as a single container
instance (max_instances = 1), so in-process locks are sufficient.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

from .agent.runner import TurnRunner
from .channel import TurnChannel
from .config import Settings
from .db import D1Error
from .schemas import Accepted, MessageOut, PostMessage
from .store import Member, Store

log = logging.getLogger(__name__)


class ConversationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ConversationService:
    def __init__(self, settings: Settings, store: Store, runner: TurnRunner):
        self.settings = settings
        self.store = store
        self.runner = runner
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: Counter[str] = Counter()
        self._tasks: set[asyncio.Task] = set()

    async def accept(
        self, conversation_id: str, body: PostMessage, *, streaming: bool
    ) -> tuple[Accepted, TurnChannel | None]:
        # Check ownership before writing anything, so a rejected request can't rename the member.
        conversation = await self.store.get_conversation(conversation_id)
        if conversation is not None and conversation.member_id != body.member.id:
            raise ConversationError(409, "This conversation belongs to a different member.")
        member = await self.store.upsert_member(body.member.id, body.member.name)
        if conversation is None:
            conversation = await self.store.create_conversation(conversation_id, member.id)
            if conversation.member_id != member.id:  # another member created it first
                raise ConversationError(409, "This conversation belongs to a different member.")
            self._background(self.runner.warm_up(member.id))

        duplicate = await self._duplicate(conversation_id, body.message_id)
        if duplicate:
            return duplicate, None
        try:
            message = await self.store.add_message(conversation_id, "member", body.text, body.message_id)
        except D1Error:
            # Lost a race with an identical retry; report it like any other duplicate.
            duplicate = await self._duplicate(conversation_id, body.message_id)
            if duplicate:
                return duplicate, None
            raise

        channel = TurnChannel(
            self.store, conversation_id, streaming=streaming, holding_after=self.settings.holding_message_after_seconds
        )
        channel.emit("message.created", MessageOut.of(message).model_dump())
        # Count the turn before the status write, so a turn finishing meanwhile doesn't mark it idle.
        self._pending[conversation_id] += 1
        try:
            await self.store.set_status(conversation_id, "processing")
        except Exception:
            self._release(conversation_id)
            raise
        channel.start()  # the 12-second clock starts when the member's message is accepted
        self._background(self._process(member, conversation_id, body.text, channel))
        return Accepted(message_id=message.id, conversation_id=conversation_id, status="accepted"), channel

    def _background(self, coro) -> None:
        """Run a task that ``drain`` waits for on shutdown."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _duplicate(self, conversation_id: str, message_id: str) -> Accepted | None:
        existing = await self.store.get_message(message_id)
        if existing is None:
            return None
        if existing.conversation_id != conversation_id:
            raise ConversationError(409, "message_id has already been used in another conversation.")
        return Accepted(message_id=message_id, conversation_id=conversation_id, status="duplicate")

    async def _process(self, member: Member, conversation_id: str, text: str, channel: TurnChannel) -> None:
        status = "error"
        try:
            lock = self._locks.setdefault(conversation_id, asyncio.Lock())
            async with lock:
                status = await self.runner.run(member, conversation_id, text, channel)
        except Exception:
            log.exception("Unhandled error processing conversation %s", conversation_id)
        finally:
            if self._release(conversation_id):
                try:
                    await self.store.set_status(conversation_id, "idle")
                except Exception:
                    log.exception("Could not mark conversation %s idle", conversation_id)
            await channel.close(status)

    def _release(self, conversation_id: str) -> bool:
        """Count one turn as done. True when it was the conversation's last pending turn."""
        self._pending[conversation_id] -= 1
        if self._pending[conversation_id] > 0:
            return False
        del self._pending[conversation_id]
        self._locks.pop(conversation_id, None)
        return True

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
