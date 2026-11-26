"""Mock calendar REST API.

Any member id has a calendar: the first request for an unknown member generates
and stores it (deterministically from the member id), so callers never create one.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator

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


@router.delete("/{member_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(member_id: str, event_id: str, request: Request):
    if not await service(request).delete_event(member_id, event_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
