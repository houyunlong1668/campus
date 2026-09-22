CREATE TABLE IF NOT EXISTS sql_queries (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    student_id VARCHAR(32) NOT NULL,
    sql_raw TEXT NOT NULL,
    sql_scoped TEXT NOT NULL,
    refused_code VARCHAR(32) NULL,
    row_count INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sq_conv (conversation_id),
    INDEX idx_sq_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
