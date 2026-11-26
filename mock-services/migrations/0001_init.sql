-- Mock services schema (Cloudflare D1)

-- One row per member, written the first time anything asks for their calendar.
CREATE TABLE IF NOT EXISTS calendars (
    member_id      TEXT PRIMARY KEY,
    seed           TEXT NOT NULL,
    traits         TEXT NOT NULL, -- JSON array of trait ids
    generated_from TEXT NOT NULL, -- first stored day, YYYY-MM-DD
    generated_to   TEXT NOT NULL, -- last stored day, YYYY-MM-DD
    created_at     TEXT NOT NULL
);

-- Every calendar event: generated ones (deterministic ids) and ones added via the API.
CREATE TABLE IF NOT EXISTS calendar_events (
    id         TEXT PRIMARY KEY,
    member_id  TEXT NOT NULL,
    title      TEXT NOT NULL,
    date       TEXT NOT NULL,
    start_time TEXT,
    end_time   TEXT,
    all_day    INTEGER NOT NULL DEFAULT 0,
    location   TEXT,
    notes      TEXT,
    category   TEXT NOT NULL,
    source     TEXT NOT NULL CHECK (source IN ('generated', 'member')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calendar_events_member_date ON calendar_events (member_id, date);

CREATE TABLE IF NOT EXISTS bookings (
    id               TEXT PRIMARY KEY,
    reference        TEXT NOT NULL UNIQUE,
    restaurant_id    TEXT NOT NULL,
    member_id        TEXT NOT NULL,
    member_name      TEXT NOT NULL,
    date             TEXT NOT NULL,
    time             TEXT NOT NULL,
    party_size       INTEGER NOT NULL,
    occasion         TEXT,
    special_requests TEXT,
    status           TEXT NOT NULL DEFAULT 'confirmed',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_slot ON bookings (restaurant_id, date, time);
CREATE INDEX IF NOT EXISTS idx_bookings_member ON bookings (member_id);
