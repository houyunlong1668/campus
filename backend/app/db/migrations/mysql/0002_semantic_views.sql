-- MySQL 没有 CREATE VIEW IF NOT EXISTS，用 CREATE OR REPLACE 保证本文件可重入
-- （迁移器只跑一次，但半途失败重跑时不能卡在"view already exists"）。
CREATE OR REPLACE VIEW v_grades (student_id, course, term, credits, score, points, teacher) AS
  SELECT student_id, course_name, term, credits, score, grade_points, teacher
  FROM enrollments;

CREATE OR REPLACE VIEW v_schedule (student_id, course, weekday, start_period, end_period, room, teacher, weeks) AS
  SELECT student_id, course_name, weekday, start_period, end_period, room, teacher,
         CONCAT(weeks_from, '-', weeks_to)
  FROM course_sections;

CREATE OR REPLACE VIEW v_makeup (student_id, course, kind, reason, scheduled_at, place, status, seats_left) AS
  SELECT student_id, course_name, kind, reason, scheduled_at, place, status, seats_left
  FROM makeup_items;

CREATE OR REPLACE VIEW v_loans (student_id, title, call_no, due_at, days_left, shelf) AS
  SELECT student_id, title, call_no, due_at, DATEDIFF(due_at, CURDATE()), shelf
  FROM library_loans
  WHERE returned_at IS NULL;
