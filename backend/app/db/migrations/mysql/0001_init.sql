CREATE TABLE IF NOT EXISTS students (
    student_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    major VARCHAR(128) NOT NULL DEFAULT '',
    class_name VARCHAR(64) NOT NULL DEFAULT '',
    college VARCHAR(128) NOT NULL DEFAULT '',
    enrolled_year INT NOT NULL DEFAULT 2023,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS courses (
    course_code VARCHAR(32) PRIMARY KEY,
    course_name VARCHAR(128) NOT NULL,
    credits DECIMAL(4,1) NOT NULL,
    teacher VARCHAR(64) NOT NULL DEFAULT '',
    college VARCHAR(128) NOT NULL DEFAULT '',
    kind VARCHAR(16) NOT NULL DEFAULT '必修',
    domain VARCHAR(16) NOT NULL DEFAULT 'hum'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS enrollments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    course_code VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    term VARCHAR(32) NOT NULL,
    credits DECIMAL(4,1) NOT NULL,
    score DECIMAL(5,1) NOT NULL,
    grade_points DECIMAL(3,1) NOT NULL DEFAULT 0,
    teacher VARCHAR(64) NOT NULL DEFAULT '',
    UNIQUE KEY uq_enrollment (student_id, course_code, term),
    INDEX idx_enroll_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS course_sections (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    course_code VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    weekday INT NOT NULL,
    start_period INT NOT NULL,
    end_period INT NOT NULL,
    room VARCHAR(64) NOT NULL DEFAULT '',
    teacher VARCHAR(64) NOT NULL DEFAULT '',
    weeks_from INT NOT NULL DEFAULT 1,
    weeks_to INT NOT NULL DEFAULT 16,
    term VARCHAR(32) NOT NULL DEFAULT '',
    INDEX idx_sections_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS makeup_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    course_code VARCHAR(32) NOT NULL DEFAULT '',
    kind VARCHAR(16) NOT NULL DEFAULT '补考',
    reason VARCHAR(256) NOT NULL DEFAULT '',
    scheduled_at DATETIME NOT NULL,
    place VARCHAR(128) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT '已报名',
    seats_left INT NULL,
    seats_total INT NULL,
    term VARCHAR(32) NOT NULL DEFAULT '',
    INDEX idx_makeup_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS library_loans (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    title VARCHAR(256) NOT NULL,
    call_no VARCHAR(64) NOT NULL,
    due_at DATETIME NOT NULL,
    shelf VARCHAR(128) NOT NULL DEFAULT '',
    returned_at DATETIME NULL,
    INDEX idx_loans_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conv_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_msg_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS tool_calls (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    tool_name VARCHAR(64) NOT NULL,
    args_json TEXT NOT NULL,
    ok TINYINT NOT NULL,
    error TEXT,
    latency_ms INT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tc_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
