"""Restaurant directory + booking service exposed over MCP (streamable HTTP at /mcp)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..cities import CITIES
from .service import BookingError, RestaurantService

mcp = MCPServer(
    name="halcyon-restaurants",
    title="Halcyon restaurant directory & bookings (mock)",
    version="1.0.0",
    instructions=(
        "Mock restaurant directory for London, Paris, New York and Los Angeles only. Search first (always "
        "with a city), then check availability for a specific restaurant/date/party size, then "
        "create_booking with one of the returned times. Dates and times are the restaurant's local time; "
        "prices are in the city's currency."
    ),
)

_service: RestaurantService | None = None


def bind_service(service: RestaurantService) -> None:
    global _service
    _service = service


def svc() -> RestaurantService:
    if _service is None:
        raise ToolError("Restaurant service is not ready")
    return _service


Date = Annotated[dt.date, Field(description="Date as YYYY-MM-DD")]
Time = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="24h time HH:MM")]
PartySize = Annotated[int, Field(ge=1, le=20, description="Number of guests")]
CityId = Literal["london", "paris", "new_york", "los_angeles"]
assert set(CityId.__args__) == set(CITIES), "CityId must list exactly the covered cities"


@mcp.tool()
async def search_restaurants(
    city: Annotated[
        CityId,
        Field(description="City to search: london, paris, new_york or los_angeles. No other cities are covered."),
    ],
    query: Annotated[
        str | None, Field(description="Free-text keywords matched against name, description and tags")
    ] = None,
    cuisine: Annotated[str | None, Field(description="e.g. Italian, Japanese, French, Indian, Seafood")] = None,
    area: Annotated[
        str | None,
        Field(
            description="Neighbourhood within the city, e.g. Soho (London), Le Marais (Paris), "
            "West Village (New York), Santa Monica (Los Angeles)"
        ),
    ] = None,
    min_price_level: Annotated[int | None, Field(ge=1, le=4, description="1 (cheap) .. 4 (very expensive)")] = None,
    max_price_level: Annotated[int | None, Field(ge=1, le=4, description="1 (cheap) .. 4 (very expensive)")] = None,
    tags: Annotated[
        list[str] | None,
        Field(
            description="Preferred vibe tags, ranked not filtered: romantic, quiet, lively, special_occasion, "
            "business, views, terrace, tasting_menu, group_friendly, casual, pre_theatre, late_night, "
            "wine_list, natural_wine, wine_bar, cocktails"
        ),
    ] = None,
    dietary: Annotated[
        list[str] | None, Field(description="Required dietary options: vegetarian, vegan, gluten_free, halal, kosher")
    ] = None,
    party_size: PartySize | None = None,
    date: Annotated[
        dt.date | None, Field(description="If set with time, each result includes open times near it")
    ] = None,
    time: Annotated[str | None, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Preferred time HH:MM")] = None,
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict[str, Any]:
    """Search one city's restaurants. Returns the best matches, optionally with availability."""
    service = svc()
    matches = service.search(
        city=city,
        query=query,
        cuisine=cuisine,
        area=area,
        min_price_level=min_price_level,
        max_price_level=max_price_level,
        tags=tags,
        dietary=dietary,
        party_size=party_size,
    )
    results = []
    for r in matches[:limit]:
        item = service.summary(r)
        if date is not None:
            try:
                avail = await service.availability(r["id"], date, party_size or 2, time)
            except BookingError as exc:
                raise ToolError(str(exc)) from exc
            item["available_times"] = avail["available_times"]
            if avail["note"]:
                item["availability_note"] = avail["note"]
        results.append(item)
    return {"count": len(results), "total_matches": len(matches), "results": results}


@mcp.tool()
async def get_restaurant(restaurant_id: str) -> dict[str, Any]:
    """Full details for one restaurant: address, opening days, service times, max party size."""
    try:
        return svc().details(restaurant_id)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def check_availability(
    restaurant_id: str,
    date: Date,
    party_size: PartySize,
    preferred_time: Annotated[str | None, Field(description="HH:MM; results are sorted by closeness")] = None,
) -> dict[str, Any]:
    """Open booking times for a restaurant on a date for a party size."""
    try:
        return await svc().availability(restaurant_id, date, party_size, preferred_time)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def create_booking(
    restaurant_id: str,
    date: Date,
    time: Time,
    party_size: PartySize,
    member_id: Annotated[str, Field(description="Member making the booking")],
    member_name: Annotated[str, Field(description="Name the booking is held under")],
    occasion: Annotated[str | None, Field(description="e.g. birthday, anniversary, business")] = None,
    special_requests: Annotated[str | None, Field(description="Dietary needs, seating preferences, etc.")] = None,
) -> dict[str, Any]:
    """Book a table. Only call after the member has confirmed restaurant, date, time and party size."""
    try:
        return await svc().create_booking(
            restaurant_id=restaurant_id,
            day=date,
            time=time,
            party_size=party_size,
            member_id=member_id,
            member_name=member_name,
            occasion=occasion,
            special_requests=special_requests,
        )
    except BookingError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def list_bookings(
    member_id: str,
    include_past: Annotated[bool, Field(description="Include past bookings (useful for favourites)")] = True,
) -> dict[str, Any]:
    """A member's bookings, newest first."""
    bookings = await svc().list_bookings(member_id, include_past)
    return {"count": len(bookings), "bookings": bookings}


@mcp.tool()
async def cancel_booking(
    booking_id: Annotated[str, Field(description="booking_id or reference (HC-XXXXXX)")],
    member_id: str,
) -> dict[str, Any]:
    """Cancel one of the member's upcoming bookings. Only call after the member has confirmed the cancellation."""
    try:
        return await svc().cancel_booking(booking_id, member_id)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def modify_booking(
    booking_id: Annotated[str, Field(description="booking_id or reference (HC-XXXXXX)")],
    member_id: str,
    date: Annotated[dt.date | None, Field(description="New date, YYYY-MM-DD; omit to keep")] = None,
    time: Annotated[
        str | None, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="New time HH:MM; omit to keep")
    ] = None,
    party_size: Annotated[int | None, Field(ge=1, le=20, description="New number of guests; omit to keep")] = None,
    occasion: Annotated[str | None, Field(description="Replaces the occasion; omit to keep")] = None,
    special_requests: Annotated[str | None, Field(description="Replaces the special requests; omit to keep")] = None,
) -> dict[str, Any]:
    """Change an upcoming booking at the same restaurant: date, time, party size, occasion or requests.

    Keeps the same reference. If the new slot has no table, the booking is left unchanged. To move to a
    different restaurant, create_booking there first, then cancel_booking the old one. Only call after the
    member has confirmed the change. The result includes the previous date, time and party size.
    """
    try:
        return await svc().modify_booking(
            booking_id,
            member_id,
            day=date,
            time=time,
            party_size=party_size,
            occasion=occasion,
            special_requests=special_requests,
        )
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
