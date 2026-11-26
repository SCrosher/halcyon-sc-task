"""Halcyon agent API."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .agent.llm import ClaudeClient
from .agent.runner import TurnRunner
from .agent.tools.restaurants import RestaurantCatalog
from .channel import TURN_COMPLETED
from .config import Settings, get_settings
from .conversations import ConversationError, ConversationService
from .db import D1Database
from .schemas import Accepted, ConversationOut, MemoriesOut, MemoryOut, MessageOut, MessagesOut, PostMessage
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

SSE_KEEPALIVE_SECONDS = 15.0


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = D1Database(settings.d1.api_url, settings.d1.account_id, settings.d1.database_id, settings.d1.api_token)
        store = Store(db)
        await store.reset_processing()
        mock_http = httpx2.AsyncClient(
            base_url=settings.mock_services_url.rstrip("/"),
            headers=settings.mock_services_headers,
            timeout=httpx2.Timeout(20.0),
        )
        llm = ClaudeClient(settings)
        runner = TurnRunner(settings, store, llm, mock_http, RestaurantCatalog(settings))
        app.state.store = store
        app.state.conversations = ConversationService(settings, store, runner)
        yield
        await app.state.conversations.drain()
        await llm.aclose()
        await mock_http.aclose()
        await db.close()

    app = FastAPI(title="Halcyon agent API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        supplied = credentials.credentials.encode() if credentials else b""
        if not any(secrets.compare_digest(supplied, token.encode()) for token in settings.api_tokens):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def store(request: Request) -> Store:
        return request.app.state.store

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post(
        "/conversations/{conversation_id}/messages",
        dependencies=[Depends(authorize)],
        status_code=status.HTTP_202_ACCEPTED,
        response_model=Accepted,
        responses={
            200: {"description": "Server-sent events when streaming is requested", "content": {"text/event-stream": {}}}
        },
    )
    async def post_message(
        conversation_id: str,
        body: PostMessage,
        request: Request,
        stream: bool = Query(False, description="Stream the turn as server-sent events instead of answering 202"),
    ):
        streaming = stream or "text/event-stream" in request.headers.get("accept", "")
        try:
            accepted, channel = await request.app.state.conversations.accept(conversation_id, body, streaming=streaming)
        except ConversationError as exc:
            raise HTTPException(exc.status_code, detail=exc.detail) from exc
        if channel is None or channel.events is None:
            return JSONResponse(accepted.model_dump(), status_code=status.HTTP_202_ACCEPTED)
        return StreamingResponse(
            _sse(channel.events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/conversations/{conversation_id}/messages", dependencies=[Depends(authorize)], response_model=MessagesOut)
    async def list_messages(conversation_id: str, request: Request):
        if await store(request).get_conversation(conversation_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        messages = await store(request).list_messages(conversation_id)
        return MessagesOut(messages=[MessageOut.of(m) for m in messages])

    @app.get("/conversations/{conversation_id}", dependencies=[Depends(authorize)], response_model=ConversationOut)
    async def get_conversation(conversation_id: str, request: Request):
        conversation = await store(request).get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        return ConversationOut.of(conversation)

    @app.get("/members/{member_id}/memories", dependencies=[Depends(authorize)], response_model=MemoriesOut)
    async def list_memories(member_id: str, request: Request):
        memories = await store(request).list_memories(member_id)
        return MemoriesOut(memories=[MemoryOut.of(m) for m in memories])

    return app


async def _sse(events: asyncio.Queue[tuple[str, dict[str, Any]]]) -> AsyncIterator[str]:
    """Relay a turn's events; the turn itself carries on if the client disconnects."""
    while True:
        try:
            event, data = await asyncio.wait_for(events.get(), timeout=SSE_KEEPALIVE_SECONDS)
        except TimeoutError:
            yield ": keepalive\n\n"
            continue
        yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        if event == TURN_COMPLETED:
            return


app = create_app()
