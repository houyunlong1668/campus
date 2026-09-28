ALTER TABLE tool_calls ADD COLUMN step_details_json TEXT NOT NULL;
CREATE TABLE IF NOT EXISTS makeup_registrations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NOT NULL,
    course_code VARCHAR(32) NOT NULL,
    course_name VARCHAR(128) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT '补考',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_makeup_reg (student_id, course_code)
);
