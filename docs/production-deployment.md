# 生产部署

Compose 拓扑为 db -> backend -> frontend。数据库只在 Compose 网络内提供服务，前端 Nginx 对外暴露 FRONTEND_PORT（默认 5173），并把 /api/ 转发到后端。

## 前置条件

- Docker Engine 24+ 与 Docker Compose v2；建议 2 vCPU、4 GB RAM、20 GB 可用磁盘。
- 生产环境必须替换数据库密码，并将 OA_PROVIDER=real、OA_BASE_URL、OA_API_KEY 指向已验收的 OA bridge。
- 防火墙只开放前端端口；不要公开 PostgreSQL 端口。

## 启动与检查

执行 Copy-Item .env.example .env，编辑 POSTGRES_PASSWORD、OA_PROVIDER、OA_BASE_URL、OA_API_KEY，然后依次运行 docker compose config --quiet、docker compose up -d --build、docker compose ps。检查 docker compose logs --tail=100 backend frontend，并访问 http://127.0.0.1:5173/healthz 与 /api/readiness。

后端容器启动时只执行 alembic upgrade head，不会清理业务表；随后通过 healthz 和 readiness 验证服务与 OA 能力。

## 备份与恢复

使用 docker exec oa-agent-db pg_dump -U oa -d oa_agent -Fc > data/backups/oa_agent_TIMESTAMP.dump 创建备份。恢复前停止 backend 和 frontend，再用 pg_restore -U oa -d oa_agent --clean --if-exists 恢复到明确选定的目标，最后启动服务。备份应复制到主机外部存储并定期演练。

## 回滚

切换到上一组已验证镜像或源码版本后，运行 docker compose up -d --no-deps backend frontend。数据库迁移遵循向前兼容原则；不得使用 docker compose down -v、dropdb 或清空卷回滚。
