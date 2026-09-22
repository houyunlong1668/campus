-- 语义层（spec 4.1）：模型只见这四个视图，列刻意收窄、命名口语化。
-- student_id 是第一列但不进 schema 提示——改写器需要它，模型不需要知道它存在。
-- SQLite 方言：`||` 代替 CONCAT，julianday 相减代替 DATEDIFF。
CREATE VIEW IF NOT EXISTS v_grades (student_id, course, term, credits, score, points, teacher) AS
  SELECT student_id, course_name, term, credits, score, grade_points, teacher
  FROM enrollments;

CREATE VIEW IF NOT EXISTS v_schedule (student_id, course, weekday, start_period, end_period, room, teacher, weeks) AS
  SELECT student_id, course_name, weekday, start_period, end_period, room, teacher,
         weeks_from || '-' || weeks_to
  FROM course_sections;

CREATE VIEW IF NOT EXISTS v_makeup (student_id, course, kind, reason, scheduled_at, place, status, seats_left) AS
  SELECT student_id, course_name, kind, reason, scheduled_at, place, status, seats_left
  FROM makeup_items;

CREATE VIEW IF NOT EXISTS v_loans (student_id, title, call_no, due_at, days_left, shelf) AS
  SELECT student_id, title, call_no, due_at,
         CAST(julianday(date(due_at)) - julianday(date('now', 'localtime')) AS INTEGER),
         shelf
  FROM library_loans
  WHERE returned_at IS NULL;
