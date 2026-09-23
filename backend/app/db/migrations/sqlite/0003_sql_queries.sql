CREATE TABLE IF NOT EXISTS sql_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    student_id TEXT NOT NULL REFERENCES students(student_id),
    sql_raw TEXT NOT NULL,
    sql_scoped TEXT NOT NULL DEFAULT '',
    refused_code TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
