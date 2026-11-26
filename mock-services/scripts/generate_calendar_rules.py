"""Regenerate app/calendar/rules.json with Claude.

Claude writes the *rules* (a library of generic lifestyle traits, their weekly patterns and vocabulary);
the generator turns them into calendars with deterministic code. Run this only when you
want a fresh trait library - the output is checked in. Existing members keep their stored
calendars; only members first seen afterwards get the new traits.

    pip install -e ".[rules]"
    python scripts/generate_calendar_rules.py            # writes app/calendar/rules.json
    python scripts/generate_calendar_rules.py --dry-run  # prints instead

Requires ANTHROPIC_API_KEY (read from the repo-root .env if present).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.calendar.rules import RULES_PATH, CalendarRules  # noqa: E402

MODEL = "claude-opus-5-5"

PROMPT = """Design a trait library for a realistic mock calendar generator used to test a dining-concierge agent.

We know nothing about a member before generating their calendar, so the traits must be generic: they should
apply to anyone, anywhere. No cities, neighbourhoods, venues or region-specific customs; locations are generic
("Office", "Gym", "Home", "School", "Video call"). All times are local wall-clock times.

Each member gets traits picked at random per group, so write these trait_groups (pick = [min, max] per member):
- work [1, 1]: e.g. office 9-5, hybrid, shift worker on a rota, freelancer, retired, student
- household [1, 1]: e.g. no dependants, young children, teenagers, caring for a parent
- fitness [1, 1]: e.g. early gym, evening classes, weekend runner, team sport, none (a trait may have no patterns)
- social [1, 1]: e.g. busy, occasional, homebody
- extras [0, 2]: e.g. travels for work, weekly hobby class, volunteering, book club, date nights
Give every trait a weight (relative likelihood within its group) and 0-5 patterns:
  - kind "recurring": fixed start time (HH:MM) on given weekdays, e.g. stand-ups, school runs, classes
  - kind "random": a start picked in [window_start, window_end] with durations_min options and an optional
    count [min, max] for how many happen that day (e.g. meetings [2, 4])
  - kind "all_day": whole-day blocks such as travel, with a low probability
  - days use 0=Monday .. 6=Sunday; probability is per eligible day; week_parity "odd"/"even" for rotas
  - titles and locations may use {placeholders}; vocab must define every placeholder used

Traits from different groups are combined and overlapping events are skipped, so keep each trait to its own part
of the day/week. Make the mix feel real: weekday daytimes driven by work; evenings and weekends by household,
fitness and social traits, so a request like "dinner for 2 on Thursday" sometimes clashes with an existing
commitment. Use fictional company names and first names only - no real people or businesses. Trait ids must be
unique across groups and pattern ids unique within a trait.

Set version 2, generated_by to the model you are, a one-paragraph notes field describing the design, and
rules: max_events_per_day 8, placement_attempts 4, min_gap_min 0. Leave seed as "TO_BE_REPLACED"."""


def load_root_env() -> None:
    env_file = ROOT.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the rules instead of writing them")
    args = parser.parse_args()

    load_root_env()
    client = anthropic.Anthropic()

    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        output_config={"effort": "high"},
        output_format=CalendarRules,
        messages=[{"role": "user", "content": PROMPT}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        print("Claude declined the request.", file=sys.stderr)
        return 1
    if message.stop_reason == "max_tokens":
        print("Output was truncated; raise max_tokens and retry.", file=sys.stderr)
        return 1

    rules = message.parsed_output
    if rules is None:
        print("No structured output returned.", file=sys.stderr)
        return 1
    # The seed is ours, not the model's: it makes calendars unique to this rules version.
    rules.seed = f"halcyon-calendar-{secrets.token_hex(4)}"
    rules = CalendarRules.model_validate(rules.model_dump())  # enforce every validator

    output = rules.model_dump_json(indent=2) + "\n"
    if args.dry_run:
        print(output)
    else:
        RULES_PATH.write_text(output, encoding="utf-8")
        traits = sum(len(g.traits) for g in rules.trait_groups)
        print(f"Wrote {RULES_PATH} ({traits} traits). Run the tests before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
