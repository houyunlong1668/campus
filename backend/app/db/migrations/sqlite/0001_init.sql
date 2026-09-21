CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    major TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL DEFAULT '',
    college TEXT NOT NULL DEFAULT '',
    enrolled_year INTEGER NOT NULL DEFAULT 2023,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS courses (
    course_code TEXT PRIMARY KEY,
    course_name TEXT NOT NULL,
    credits REAL NOT NULL,
    teacher TEXT NOT NULL DEFAULT '',
    college TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '必修',
    domain TEXT NOT NULL DEFAULT 'hum'
);
CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    course_name TEXT NOT NULL,
    term TEXT NOT NULL,
    credits REAL NOT NULL,
    score REAL NOT NULL,
    grade_points REAL NOT NULL DEFAULT 0,
    teacher TEXT NOT NULL DEFAULT '',
    UNIQUE(student_id, course_code, term)
);
CREATE TABLE IF NOT EXISTS course_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    course_name TEXT NOT NULL,
    weekday INTEGER NOT NULL,
    start_period INTEGER NOT NULL,
    end_period INTEGER NOT NULL,
    room TEXT NOT NULL DEFAULT '',
    teacher TEXT NOT NULL DEFAULT '',
    weeks_from INTEGER NOT NULL DEFAULT 1,
    weeks_to INTEGER NOT NULL DEFAULT 16,
    term TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS makeup_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    course_name TEXT NOT NULL,
    course_code TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '补考',
    reason TEXT NOT NULL DEFAULT '',
    scheduled_at TEXT NOT NULL,
    place TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '已报名',
    seats_left INTEGER,
    seats_total INTEGER,
    term TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS library_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    title TEXT NOT NULL,
    call_no TEXT NOT NULL,
    due_at TEXT NOT NULL,
    shelf TEXT NOT NULL DEFAULT '',
    returned_at TEXT
);
-- 新形状：不再有 session_id 列（S1 兼容写法随之删除，见 Task 3）
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    latency_ms INTEGER NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
