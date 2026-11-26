"""Holding messages sent when nothing has reached the member for a while."""

from __future__ import annotations

from collections import Counter
from typing import Literal

Activity = Literal["starting", "calendar", "search", "availability", "booking", "bookings", "memory", "composing"]

HOLDING_MESSAGES: dict[Activity, list[str]] = {
    "starting": ["One moment, please…", "Bear with me a moment…"],
    "calendar": ["Still looking at your diary…", "Nearly finished with your diary…"],
    "search": ["Still considering a few options for you…", "Narrowing down the best tables…"],
    "availability": ["Checking which tables are free…", "Still confirming availability…"],
    "booking": ["Finalising your reservation now…", "Nearly done with your reservation…"],
    "bookings": ["Looking back through your reservations…"],
    "memory": ["One moment, please…"],
    "composing": ["Just putting that together for you…", "Almost there…", "One moment more…"],
}


class HoldingMessages:
    """Picks a holding message for the current activity, cycling so it doesn't repeat itself."""

    def __init__(self) -> None:
        self._used: Counter[Activity] = Counter()

    def next(self, activity: Activity) -> str:
        options = HOLDING_MESSAGES.get(activity) or HOLDING_MESSAGES["starting"]
        text = options[self._used[activity] % len(options)]
        self._used[activity] += 1
        return text
