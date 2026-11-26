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
    return response.json() if response.content else None  # DELETE answers 204 with no body


def _compact(event: dict[str, Any]) -> dict[str, Any]:
    keep = ("title", "date", "start_time", "end_time", "all_day", "location", "category", "notes")
    # event_id lets the model update or remove the event; notes hold a booking's reference.
    compact = {"event_id": event["id"]} if event.get("id") else {}
    compact.update({k: event[k] for k in keep if event.get(k) not in (None, False)})
    if "date" in compact:
        compact["weekday"] = _weekday(compact["date"])
    return compact


def _weekday(iso: str) -> str:
    # Spelled out so the model never has to work out a weekday (it gets them wrong).
    return date.fromisoformat(iso).strftime("%A")


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
        "weekday": _weekday(data["date"]),
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


def _event_path(event_id: str) -> str:
    return f"/events/{quote(event_id, safe='')}"


async def _update(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    changes = {k: v for k, v in args.items() if k != "event_id"}
    if not changes:
        raise ToolFailure("Nothing to change: pass at least one field to update")
    if "date" in changes:
        _parse_date(changes["date"], "date")
    data = await _request(ctx, "PATCH", _event_path(args["event_id"]), json=changes)
    return {"updated": True, "event": _compact(data["event"])}


async def _remove(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    await _request(ctx, "DELETE", _event_path(args["event_id"]))
    return {"removed": True, "event_id": args["event_id"]}


EVENT_ID = {"type": "string", "description": "event_id from calendar_list_events or calendar_check_availability"}

CALENDAR_TOOLS = [
    Tool(
        name="calendar_list_events",
        description=(
            f"List the member's calendar events between two dates (inclusive, max {MAX_LIST_DAYS} days). "
            "Use for context such as what they're doing before/after dinner or which evenings are free, "
            "and to see which city they'll be in: an all-day trip event's location is the city, and flights "
            "show travel days."
        ),
        parameters=object_schema({"start_date": DATE, "end_date": DATE}, ["start_date"]),
        source="calendar",
        activity="calendar",
        handler=_list_events,
    ),
    Tool(
        name="calendar_check_availability",
        description=(
            "Check whether the member is free in a time window on a date; returns any conflicts and the rest "
            "of the day, including any all-day trip event that shows which city they're in."
        ),
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
    Tool(
        name="calendar_update_event",
        description=(
            "Change an existing diary event; fields you leave out stay as they are. Use to keep a booking's "
            "entry in step after modify_booking (new date or time, party size in the title), or when the "
            "member asks to change an event. Only after the member has asked for or confirmed the change."
        ),
        parameters=object_schema(
            {
                "event_id": EVENT_ID,
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "date": DATE,
                "start_time": TIME,
                "end_time": TIME,
                "location": {"type": "string", "maxLength": 300},
                "notes": {"type": "string", "maxLength": 1000},
            },
            ["event_id"],
        ),
        source="calendar",
        activity="calendar",
        handler=_update,
    ),
    Tool(
        name="calendar_remove_event",
        description=(
            "Remove an event from the member's diary, e.g. a cancelled booking's entry. Only after the member "
            "has asked for or confirmed it; it can't be undone."
        ),
        parameters=object_schema({"event_id": EVENT_ID}, ["event_id"]),
        source="calendar",
        activity="calendar",
        handler=_remove,
    ),
]
