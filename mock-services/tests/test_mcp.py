"""Exercise the restaurant MCP server in-process through the real MCP client."""

import json
from datetime import timedelta

from mcp import Client

from app.restaurants.mcp_server import bind_service, mcp

from .conftest import TODAY


async def test_tools_are_listed(restaurants):
    bind_service(restaurants)
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "search_restaurants",
        "get_restaurant",
        "check_availability",
        "create_booking",
        "list_bookings",
        "cancel_booking",
    }
    booking_schema = tools["create_booking"].input_schema
    required = {"restaurant_id", "date", "time", "party_size", "member_id", "member_name"}
    assert required <= set(booking_schema["required"])


async def test_search_and_book_over_mcp(restaurants):
    bind_service(restaurants)
    thursday = (TODAY + timedelta(days=7)).isoformat()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "search_restaurants",
            {"tags": ["romantic"], "min_price_level": 3, "date": thursday, "time": "19:30", "party_size": 2},
        )
        assert not result.is_error
        payload = result.structured_content or json.loads(result.content[0].text)
        assert payload["results"]
        option = next(r for r in payload["results"] if r.get("available_times"))

        booked = await client.call_tool(
            "create_booking",
            {
                "restaurant_id": option["restaurant_id"],
                "date": thursday,
                "time": option["available_times"][0],
                "party_size": 2,
                "member_id": "m1",
                "member_name": "Jane Doe",
                "occasion": "anniversary",
            },
        )
        assert not booked.is_error
        booking = booked.structured_content or json.loads(booked.content[0].text)
        assert booking["status"] == "confirmed"

        bad = await client.call_tool("get_restaurant", {"restaurant_id": "nope"})
        assert bad.is_error
        assert "Unknown restaurant_id" in bad.content[0].text
