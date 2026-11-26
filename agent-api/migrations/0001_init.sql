-- Agent API schema (Cloudflare D1)

CREATE TABLE IF NOT EXISTS members (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Durable facts the agent has learned about a member.
CREATE TABLE IF NOT EXISTS memories (
    id         TEXT PRIMARY KEY,
    member_id  TEXT NOT NULL REFERENCES members (id),
    category   TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_member ON memories (member_id);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    member_id  TEXT NOT NULL REFERENCES members (id),
    status     TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle', 'processing')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Public conversation messages (what GET /conversations/{id}/messages returns).
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations (id),
    role            TEXT NOT NULL CHECK (role IN ('member', 'assistant')),
    text            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, created_at);

-- Full model transcript (Claude API message params incl. tool calls), append-only.
CREATE TABLE IF NOT EXISTS transcript_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations (id),
    entry           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transcript_conversation ON transcript_entries (conversation_id, id);
