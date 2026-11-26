"""Calendar storage: generate a member's calendar on first use, then serve it from D1."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from ..db import D1Database
from .generator import Event, choose_traits, generate_range, to_minutes
from .geography import home_city
from .rules import CalendarRules, Trait

WINDOW_DAYS_BACK = 14
WINDOW_DAYS_AHEAD = 90
# Calendars are generated on demand, so requested dates must stay near today or one request
# could generate decades of events.
MAX_DAYS_BACK = 366
MAX_DAYS_AHEAD = 366
EVENT_COLUMNS = (
    "id",
    "member_id",
    "title",
    "date",
    "start_time",
    "end_time",
    "all_day",
    "location",
    "notes",
    "category",
    "source",
    "created_at",
)
# D1 allows at most 100 bound parameters per statement.
ROWS_PER_INSERT = 100 // len(EVENT_COLUMNS)
STATEMENTS_PER_BATCH = 50


class DateOutOfRange(ValueError):
    pass


class CalendarService:
    def __init__(self, db: D1Database, rules: CalendarRules, today: Callable[[], date] | None = None):
        self.db = db
        self.rules = rules
        self._today = today or (lambda: datetime.now(UTC).date())
        self._traits = {t.id: (g, t) for g in rules.trait_groups for t in g.traits}

    def _resolve_traits(self, trait_ids: list[str]) -> list[Trait]:
        # A regenerated library may drop traits; existing stored events are unaffected either way.
        return [self._traits[t][1] for t in trait_ids if t in self._traits]

    async def _insert_events(self, member_id: str, events: list[Event]) -> None:
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                e.id,
                member_id,
                e.title,
                e.date,
                e.start_time,
                e.end_time,
                1 if e.all_day else 0,
                e.location,
                None,
                e.category,
                e.source,
                now,
            )
            for e in events
        ]
        placeholders = "(" + ", ".join("?" * len(EVENT_COLUMNS)) + ")"
        statements = []
        for i in range(0, len(rows), ROWS_PER_INSERT):
            chunk = rows[i : i + ROWS_PER_INSERT]
            sql = f"INSERT OR IGNORE INTO calendar_events ({', '.join(EVENT_COLUMNS)}) VALUES " + ", ".join(
                [placeholders] * len(chunk)
            )
            statements.append((sql, [value for row in chunk for value in row]))
        for i in range(0, len(statements), STATEMENTS_PER_BATCH):
            await self.db.batch(statements[i : i + STATEMENTS_PER_BATCH])

    async def _calendar_row(self, member_id: str) -> dict | None:
        rows = (await self.db.execute("SELECT * FROM calendars WHERE member_id = ?", (member_id,))).rows
        return rows[0] if rows else None

    async def ensure(self, member_id: str, start: date | None = None, end: date | None = None) -> dict:
        """Make sure the member's calendar exists and covers [start, end]. Returns the calendar row."""
        today = self._today()
        earliest, latest = today - timedelta(days=MAX_DAYS_BACK), today + timedelta(days=MAX_DAYS_AHEAD)
        for day in (start, end):
            if day is not None and not earliest <= day <= latest:
                raise DateOutOfRange(f"dates must be between {earliest.isoformat()} and {latest.isoformat()}")
        row = await self._calendar_row(member_id)
        if row is None:
            first = min(today - timedelta(days=WINDOW_DAYS_BACK), start or today)
            last = max(today + timedelta(days=WINDOW_DAYS_AHEAD), end or today)
            traits = choose_traits(self.rules, member_id)
            await self._insert_events(member_id, generate_range(self.rules, member_id, traits, first, last))
            # Deterministic ids + INSERT OR IGNORE make a concurrent first request harmless.
            await self.db.execute(
                "INSERT OR IGNORE INTO calendars (member_id, seed, traits, generated_from, generated_to, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    member_id,
                    self.rules.seed,
                    json.dumps([t.id for t in traits]),
                    first.isoformat(),
                    last.isoformat(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            return await self._calendar_row(member_id)

        stored_from = date.fromisoformat(row["generated_from"])
        stored_to = date.fromisoformat(row["generated_to"])
        gaps = []
        if start and start < stored_from:
            gaps.append((start, stored_from - timedelta(days=1)))
        if end and end > stored_to:
            gaps.append((stored_to + timedelta(days=1), end))
        if gaps:
            traits = self._resolve_traits(json.loads(row["traits"]))
            rules = self.rules.model_copy(update={"seed": row["seed"]})
            for gap_start, gap_end in gaps:
                await self._insert_events(member_id, generate_range(rules, member_id, traits, gap_start, gap_end))
            new_from, new_to = min(stored_from, start or stored_from), max(stored_to, end or stored_to)
            await self.db.execute(
                "UPDATE calendars SET generated_from = ?, generated_to = ? WHERE member_id = ?",
                (new_from.isoformat(), new_to.isoformat(), member_id),
            )
            row = {**row, "generated_from": new_from.isoformat(), "generated_to": new_to.isoformat()}
        return row

    async def profile(self, member_id: str) -> dict:
        row = await self.ensure(member_id)
        traits = []
        for trait_id in json.loads(row["traits"]):
            if trait_id in self._traits:
                group, trait = self._traits[trait_id]
                traits.append({"group": group.id, "id": trait.id, "label": trait.label})
        home = home_city(row["seed"], member_id)
        return {
            "member_id": member_id,
            "home_city": home.name,
            "traits": traits,
            "generated_from": row["generated_from"],
            "generated_to": row["generated_to"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _event(row: dict) -> Event:
        return Event(
            id=row["id"],
            title=row["title"],
            date=row["date"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            all_day=bool(int(row["all_day"])),
            location=row["location"],
            category=row["category"],
            source=row["source"],
            notes=row["notes"],
        )

    async def events(self, member_id: str, start: date, end: date) -> list[Event]:
        await self.ensure(member_id, start, end)
        rows = (
            await self.db.execute(
                "SELECT * FROM calendar_events WHERE member_id = ? AND date >= ? AND date <= ? "
                "ORDER BY date, all_day DESC, start_time, title",
                (member_id, start.isoformat(), end.isoformat()),
            )
        ).rows
        return [self._event(r) for r in rows]

    async def availability(self, member_id: str, day: date, start_time: str, end_time: str) -> dict:
        day_events = await self.events(member_id, day, day)
        window = (to_minutes(start_time), to_minutes(end_time))
        conflicts = []
        for event in day_events:
            interval = event.interval()
            # All-day events (e.g. a trip, which says which city they're in) don't block a time window.
            if interval is not None and interval[0] < window[1] and window[0] < interval[1]:
                conflicts.append(event)
        return {
            "date": day.isoformat(),
            "start_time": start_time,
            "end_time": end_time,
            "free": not conflicts,
            "conflicts": [c.to_dict() for c in conflicts],
            "day_events": [e.to_dict() for e in day_events],
        }

    async def add_event(
        self,
        member_id: str,
        *,
        title: str,
        day: date,
        start_time: str | None,
        end_time: str | None,
        all_day: bool,
        location: str | None,
        notes: str | None,
        category: str,
    ) -> Event:
        await self.ensure(member_id, day, day)
        event = Event(
            str(uuid.uuid4()),
            title,
            day.isoformat(),
            start_time,
            end_time,
            all_day,
            location,
            category,
            "member",
            notes,
        )
        await self.db.execute(
            f"INSERT INTO calendar_events ({', '.join(EVENT_COLUMNS)}) VALUES ({', '.join('?' * len(EVENT_COLUMNS))})",
            (
                event.id,
                member_id,
                title,
                event.date,
                start_time,
                end_time,
                1 if all_day else 0,
                location,
                notes,
                category,
                "member",
                datetime.now(UTC).isoformat(),
            ),
        )
        return event

    async def get_event(self, member_id: str, event_id: str) -> Event | None:
        rows = (
            await self.db.execute("SELECT * FROM calendar_events WHERE member_id = ? AND id = ?", (member_id, event_id))
        ).rows
        return self._event(rows[0]) if rows else None

    async def update_event(
        self,
        member_id: str,
        event_id: str,
        *,
        title: str,
        day: date,
        start_time: str | None,
        end_time: str | None,
        all_day: bool,
        location: str | None,
        notes: str | None,
        category: str,
    ) -> Event | None:
        """Replace an event's fields (the caller merges and validates). Keeps its id and source."""
        # Moving an event may land outside the stored range; generate that first so it stays consistent.
        await self.ensure(member_id, day, day)
        result = await self.db.execute(
            "UPDATE calendar_events SET title = ?, date = ?, start_time = ?, end_time = ?, all_day = ?, "
            "location = ?, notes = ?, category = ? WHERE member_id = ? AND id = ?",
            (
                title,
                day.isoformat(),
                start_time,
                end_time,
                1 if all_day else 0,
                location,
                notes,
                category,
                member_id,
                event_id,
            ),
        )
        return await self.get_event(member_id, event_id) if result.changes else None

    async def delete_event(self, member_id: str, event_id: str) -> bool:
        result = await self.db.execute(
            "DELETE FROM calendar_events WHERE member_id = ? AND id = ?", (member_id, event_id)
        )
        return result.changes > 0
