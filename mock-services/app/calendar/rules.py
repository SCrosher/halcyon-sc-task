"""Schema for the LLM-authored calendar rules (``rules.json``).

The rules are a library of generic lifestyle *traits* (work pattern, household,
fitness, social life, extras), grouped so each member gets one coherent mix. Claude
writes the library (see ``scripts/generate_calendar_rules.py``) and it is checked in;
the generator picks traits and builds calendars with deterministic code.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

RULES_PATH = Path(__file__).with_name("rules.json")

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
Category = Literal["work", "study", "personal", "social", "fitness", "family", "health", "travel"]


class VocabEntry(BaseModel):
    key: str = Field(description="Placeholder name used in titles/locations as {key}")
    values: list[str] = Field(min_length=1)


class Pattern(BaseModel):
    id: str
    category: Category
    kind: Literal["recurring", "random", "all_day"] = Field(
        description="recurring = fixed start time; random = start picked inside a window; all_day = whole-day block"
    )
    days: list[int] = Field(description="Weekdays the pattern may occur on, 0=Monday .. 6=Sunday")
    probability: float = Field(ge=0, le=1, description="Chance of occurring on an eligible day")
    count: list[int] = Field(
        default_factory=lambda: [1, 1],
        description="[min, max] occurrences on a day the pattern fires (random kind only)",
    )
    start: str | None = Field(default=None, description="HH:MM, recurring only")
    window_start: str | None = Field(default=None, description="HH:MM, random only: earliest start")
    window_end: str | None = Field(default=None, description="HH:MM, random only: latest end")
    durations_min: list[int] = Field(default_factory=lambda: [60])
    titles: list[str] = Field(min_length=1)
    locations: list[str] = Field(default_factory=list)
    week_parity: Literal["any", "odd", "even"] = "any"

    @field_validator("start", "window_start", "window_end")
    @classmethod
    def _time(cls, value: str | None) -> str | None:
        if value is not None and not HHMM.match(value):
            raise ValueError(f"expected HH:MM, got {value!r}")
        return value

    @field_validator("count")
    @classmethod
    def _count(cls, count: list[int]) -> list[int]:
        if len(count) != 2 or not 1 <= count[0] <= count[1] <= 8:
            raise ValueError("count must be [min, max] with 1 <= min <= max <= 8")
        return count

    @field_validator("days")
    @classmethod
    def _days(cls, days: list[int]) -> list[int]:
        if not days or any(d < 0 or d > 6 for d in days):
            raise ValueError("days must be a non-empty list of 0..6")
        return days

    @model_validator(mode="after")
    def _kind_fields(self) -> Pattern:
        if self.kind == "recurring" and not self.start:
            raise ValueError(f"recurring pattern {self.id!r} needs start")
        if self.kind == "random" and not (self.window_start and self.window_end):
            raise ValueError(f"random pattern {self.id!r} needs window_start and window_end")
        return self


class Trait(BaseModel):
    id: str
    label: str
    weight: float = Field(gt=0, description="Relative chance of being picked within its group")
    patterns: list[Pattern] = Field(description="May be empty, e.g. 'no children'")


class TraitGroup(BaseModel):
    id: str
    label: str
    pick: list[int] = Field(description="[min, max] traits picked from this group per member")
    traits: list[Trait] = Field(min_length=1)

    @model_validator(mode="after")
    def _pick(self) -> TraitGroup:
        if len(self.pick) != 2 or not 0 <= self.pick[0] <= self.pick[1] <= len(self.traits):
            raise ValueError(f"group {self.id!r}: pick must be [min, max] within 0..{len(self.traits)}")
        return self


class GlobalRules(BaseModel):
    max_events_per_day: int = 8
    placement_attempts: int = 4
    min_gap_min: int = Field(default=0, description="Minimum gap between timed events")


class CalendarRules(BaseModel):
    version: int
    seed: str = Field(description="Global seed mixed into every member's RNG")
    generated_by: str
    notes: str
    rules: GlobalRules
    vocab: list[VocabEntry]
    trait_groups: list[TraitGroup] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_and_resolvable(self) -> CalendarRules:
        trait_ids = [t.id for g in self.trait_groups for t in g.traits]
        if len(trait_ids) != len(set(trait_ids)):
            raise ValueError("trait ids must be unique across groups")
        keys = {v.key for v in self.vocab}
        for group in self.trait_groups:
            for trait in group.traits:
                pattern_ids = [p.id for p in trait.patterns]
                if len(pattern_ids) != len(set(pattern_ids)):
                    raise ValueError(f"trait {trait.id!r}: pattern ids must be unique")
                for pattern in trait.patterns:
                    for text in [*pattern.titles, *pattern.locations]:
                        missing = set(re.findall(r"\{(\w+)\}", text)) - keys
                        if missing:
                            raise ValueError(f"{trait.id}/{pattern.id}: undefined placeholder(s) {sorted(missing)}")
        return self

    def vocab_map(self) -> dict[str, list[str]]:
        return {v.key: v.values for v in self.vocab}


@lru_cache
def load_rules(path: Path = RULES_PATH) -> CalendarRules:
    return CalendarRules.model_validate(json.loads(path.read_text(encoding="utf-8")))
