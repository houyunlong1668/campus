-- compose 的 MYSQL_USER 默认授予 agent_ro 对 campus.* 的全部权限；
-- 最小权限原则：S2 先全部收回（agent_ro 尚无可查对象），S3 授四个视图的 SELECT。
REVOKE ALL PRIVILEGES ON campus.* FROM 'agent_ro'@'%';
FLUSH PRIVILEGES;
