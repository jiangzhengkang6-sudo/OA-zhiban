# 回滚操作手册

1. 记录 docker compose ps、backend 日志和 /api/readiness 响应。
2. 停止写入：docker compose stop frontend backend。
3. 保留数据库卷并确认最近备份可读，禁止 docker compose down -v。
4. 切换上一组已验证镜像或源码版本，运行 docker compose up -d --no-deps backend frontend。
5. 检查 /healthz、/api/readiness 和前端 /healthz，再开放流量。
6. 若迁移不兼容，按备份恢复流程在明确目标库执行恢复，并记录恢复时间、备份编号和 trace。
