"""Mock calendar REST API.

Any member id has a calendar: the first request for an unknown member generates
and stores it (deterministically from the member id), so callers never create one.
"""

from __future__ import annotations

import datetime as dt
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, ValidationError, model_validator

from .generator import to_minutes
from .service import CalendarService

router = APIRouter(prefix="/v1/calendars", tags=["calendar"])

MAX_RANGE_DAYS = 62
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
Category = Literal["work", "study", "personal", "social", "fitness", "family", "health", "travel", "dining"]


def service(request: Request) -> CalendarService:
    return request.app.state.calendar


class NewEvent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    date: date
    start_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    all_day: bool = False
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    category: Category = "personal"

    @model_validator(mode="after")
    def _times(self) -> NewEvent:
        if self.all_day:
            self.start_time = self.end_time = None
        elif not (self.start_time and self.end_time):
            raise ValueError("start_time and end_time are required unless all_day is true")
        elif to_minutes(self.end_time) <= to_minutes(self.start_time):
            raise ValueError("end_time must be after start_time")
        return self


class EventChanges(BaseModel):
    """Fields to change on an existing event; anything left out keeps its current value."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    date: dt.date | None = None  # dt.: a field named "date" shadows the type inside the class body
    start_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    category: Category | None = None


@router.get("/{member_id}")
async def get_calendar(member_id: str, request: Request):
    """The member's calendar profile: the traits it was generated from and the stored date range."""
    return {"calendar": await service(request).profile(member_id)}


@router.get("/{member_id}/events")
async def list_events(
    member_id: str,
    request: Request,
    start: date = Query(description="First day, YYYY-MM-DD"),
    end: date | None = Query(default=None, description="Last day (inclusive); defaults to start"),
):
    end = end or start
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="end must not be before start")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"range is limited to {MAX_RANGE_DAYS} days")
    events = await service(request).events(member_id, start, end)
    return {
        "member_id": member_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "events": [e.to_dict() for e in events],
    }


@router.get("/{member_id}/availability")
async def availability(
    member_id: str,
    request: Request,
    day: date = Query(alias="date"),
    start_time: str = Query(pattern=TIME_PATTERN),
    end_time: str = Query(pattern=TIME_PATTERN),
):
    if to_minutes(end_time) <= to_minutes(start_time):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="end_time must be after start_time")
    return await service(request).availability(member_id, day, start_time, end_time)


@router.post("/{member_id}/events", status_code=status.HTTP_201_CREATED)
async def add_event(member_id: str, body: NewEvent, request: Request):
    event = await service(request).add_event(
        member_id,
        title=body.title,
        day=body.date,
        start_time=body.start_time,
        end_time=body.end_time,
        all_day=body.all_day,
        location=body.location,
        notes=body.notes,
        category=body.category,
    )
    return {"event": event.to_dict()}


@router.get("/{member_id}/events/{event_id}")
async def get_event(member_id: str, event_id: str, request: Request):
    event = await service(request).get_event(member_id, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    return {"event": event.to_dict()}


@router.patch("/{member_id}/events/{event_id}")
async def update_event(member_id: str, event_id: str, body: EventChanges, request: Request):
    svc = service(request)
    current = await svc.get_event(member_id, event_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    changes = body.model_dump(exclude_unset=True)
    merged = {
        "title": current.title,
        "date": current.date,
        "start_time": current.start_time,
        "end_time": current.end_time,
        "all_day": current.all_day,
        "location": current.location,
        "notes": current.notes,
        "category": current.category,
        **changes,
    }
    if changes.get("start_time") or changes.get("end_time"):
        merged["all_day"] = changes.get("all_day", False)  # giving times makes an all-day event a timed one
    try:
        event = NewEvent.model_validate(merged)
    except ValidationError as exc:
        detail = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail) from None
    updated = await svc.update_event(
        member_id,
        event_id,
        title=event.title,
        day=event.date,
        start_time=event.start_time,
        end_time=event.end_time,
        all_day=event.all_day,
        location=event.location,
        notes=event.notes,
        category=event.category,
    )
    if updated is None:  # deleted between the read and the write
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    return {"event": updated.to_dict()}


@router.delete("/{member_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(member_id: str, event_id: str, request: Request):
    if not await service(request).delete_event(member_id, event_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
