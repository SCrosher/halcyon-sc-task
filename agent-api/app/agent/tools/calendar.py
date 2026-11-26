"""Calendar tools backed by the mock calendar REST API."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx2

from .base import Tool, ToolFailure, TurnContext, object_schema

MAX_LIST_DAYS = 14
DATE = {"type": "string", "format": "date", "description": "YYYY-MM-DD"}
TIME = {"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d$", "description": "24h local time HH:MM"}


async def _request(ctx: TurnContext, method: str, path: str, **kwargs: Any) -> Any:
    url = f"/v1/calendars/{quote(ctx.member.id, safe='')}{path}"
    try:
        response = await ctx.mock_http.request(method, url, **kwargs)
    except httpx2.HTTPError as exc:
        raise ToolFailure(f"Calendar service unreachable: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise ToolFailure(f"Calendar service error {response.status_code}: {detail}")
    return response.json()


def _compact(event: dict[str, Any]) -> dict[str, Any]:
    keep = ("title", "date", "start_time", "end_time", "all_day", "location", "category")
    return {k: event[k] for k in keep if event.get(k) not in (None, False)}


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolFailure(f"{field} must be YYYY-MM-DD") from None


async def _list_events(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    start = _parse_date(args["start_date"], "start_date")
    end = _parse_date(args.get("end_date") or args["start_date"], "end_date")
    if end < start:
        raise ToolFailure("end_date is before start_date")
    if end - start >= timedelta(days=MAX_LIST_DAYS):
        raise ToolFailure(f"List at most {MAX_LIST_DAYS} days at a time")
    data = await _request(ctx, "GET", "/events", params={"start": start.isoformat(), "end": end.isoformat()})
    return {"start_date": data["start"], "end_date": data["end"], "events": [_compact(e) for e in data["events"]]}


async def _check(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    _parse_date(args["date"], "date")
    data = await _request(
        ctx,
        "GET",
        "/availability",
        params={"date": args["date"], "start_time": args["start_time"], "end_time": args["end_time"]},
    )
    return {
        "date": data["date"],
        "window": f"{data['start_time']}-{data['end_time']}",
        "free": data["free"],
        "conflicts": [_compact(e) for e in data["conflicts"]],
        "rest_of_day": [_compact(e) for e in data["day_events"] if e not in data["conflicts"]],
    }


async def _add(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    _parse_date(args["date"], "date")
    body = {
        "title": args["title"],
        "date": args["date"],
        "start_time": args["start_time"],
        "end_time": args["end_time"],
        "location": args.get("location"),
        "notes": args.get("notes"),
        "category": "dining",
    }
    data = await _request(ctx, "POST", "/events", json=body)
    return {"added": True, "event": _compact(data["event"])}


CALENDAR_TOOLS = [
    Tool(
        name="calendar_list_events",
        description=(
            f"List the member's calendar events between two dates (inclusive, max {MAX_LIST_DAYS} days). "
            "Use for context such as what they're doing before/after dinner or which evenings are free."
        ),
        parameters=object_schema({"start_date": DATE, "end_date": DATE}, ["start_date"]),
        source="calendar",
        activity="calendar",
        handler=_list_events,
    ),
    Tool(
        name="calendar_check_availability",
        description="Check whether the member is free in a time window on a date; returns any conflicts.",
        parameters=object_schema(
            {"date": DATE, "start_time": TIME, "end_time": TIME}, ["date", "start_time", "end_time"]
        ),
        source="calendar",
        activity="calendar",
        handler=_check,
    ),
    Tool(
        name="calendar_add_event",
        description="Add a confirmed booking to the member's calendar. Call right after a successful booking.",
        parameters=object_schema(
            {
                "title": {"type": "string", "maxLength": 200, "description": "e.g. 'Dinner at Kaito (2 people)'"},
                "date": DATE,
                "start_time": TIME,
                "end_time": TIME,
                "location": {"type": "string", "maxLength": 300},
                "notes": {"type": "string", "maxLength": 1000, "description": "e.g. booking reference"},
            },
            ["title", "date", "start_time", "end_time"],
        ),
        source="calendar",
        activity="calendar",
        handler=_add,
    ),
]
