-- S3 起 agent_ro 只能读这四个语义视图，对 enrollments 等基表仍无权限（spec 4.4 纵深）。
GRANT SELECT ON campus.v_grades TO 'agent_ro'@'%';
GRANT SELECT ON campus.v_schedule TO 'agent_ro'@'%';
GRANT SELECT ON campus.v_makeup  TO 'agent_ro'@'%';
GRANT SELECT ON campus.v_loans    TO 'agent_ro'@'%';
FLUSH PRIVILEGES;
