"""Mock services: calendar REST API (/v1/calendars) + restaurant MCP server (/mcp)."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from .calendar.routes import router as calendar_router
from .calendar.rules import load_rules
from .calendar.service import CalendarService, DateOutOfRange
from .config import Settings, get_settings
from .db import D1Database
from .restaurants.mcp_server import bind_service, mcp
from .restaurants.service import RestaurantService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

OPEN_PATHS = {"/", "/health"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # Built before the app so its session manager exists for the lifespan below.
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # Served behind Cloudflare with arbitrary Host headers; access control is the bearer token below.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = D1Database(settings.d1.api_url, settings.d1.account_id, settings.d1.database_id, settings.d1.api_token)
        app.state.calendar = CalendarService(db, load_rules(), today=settings.today)
        # Booking dates are checked against each restaurant's own local date.
        app.state.restaurants = RestaurantService(db)
        bind_service(app.state.restaurants)
        async with mcp.session_manager.run():
            yield
        await db.close()

    app = FastAPI(title="Halcyon mock services", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        token = settings.mock_services_token  # only empty locally; Settings refuses that when deployed
        if token and request.url.path not in OPEN_PATHS:
            header = request.headers.get("authorization", "")
            supplied = header[7:] if header.lower().startswith("bearer ") else ""
            if not secrets.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse(
                    {"detail": "Missing or invalid bearer token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def index():
        return {
            "service": "halcyon-mock-services",
            "calendar_api": "/v1/calendars/{member_id}",
            "restaurants_mcp": "/mcp (streamable HTTP)",
            "docs": "/docs",
        }

    @app.exception_handler(DateOutOfRange)
    async def date_out_of_range(request: Request, exc: DateOutOfRange):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    app.include_router(calendar_router)
    # Mounted last: FastAPI routes match first and everything else (i.e. /mcp) falls through.
    app.mount("/", mcp_app)
    return app


app = create_app()
