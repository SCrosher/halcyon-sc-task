"""The cities the mock services cover. Restaurants exist only in these; calendars may mention others."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    id: str
    name: str
    timezone: str
    currency: str
    symbol: str
    airport: str
    region: str  # used to size flight durations


CITIES: dict[str, City] = {
    c.id: c
    for c in (
        City("london", "London", "Europe/London", "GBP", "£", "Heathrow", "europe"),
        City("paris", "Paris", "Europe/Paris", "EUR", "€", "Charles de Gaulle", "europe"),
        City("new_york", "New York", "America/New_York", "USD", "$", "JFK", "americas"),
        City("los_angeles", "Los Angeles", "America/Los_Angeles", "USD", "$", "LAX", "americas"),
    )
}
CITY_IDS = tuple(CITIES)
