-- One row per API call (except /health). `error` is set when the request raised or returned 5xx.
CREATE TABLE IF NOT EXISTS request_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    query       TEXT,
    status_code INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    client_ip   TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_logs_created ON request_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_request_logs_errors ON request_logs (status_code, created_at);
