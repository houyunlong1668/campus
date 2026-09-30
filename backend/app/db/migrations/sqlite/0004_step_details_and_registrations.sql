ALTER TABLE tool_calls ADD COLUMN step_details_json TEXT NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS makeup_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL,
    course_name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '补考',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, course_code)
);
