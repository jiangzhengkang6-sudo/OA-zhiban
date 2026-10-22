-- OA 智能体系统 MVP：数据库初始化扩展
-- 由 docker-compose 挂载，首次启动时自动执行。
-- vector：pgvector 扩展，用于知识库向量检索
-- pgcrypto：提供 gen_random_uuid()（PG16 已内置，此处兜底兼容）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;