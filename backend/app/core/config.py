"""
OA 智能体管理系统 - 应用配置模块。

使用 pydantic-settings 读取环境变量（.env），集中管理数据库连接、模型提供方、OA 提供方、
开关阈值等运行参数。所有配置项均有默认值，保证 MVP 可开箱即用（Mock + Docker PG）。
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用运行配置（环境变量可覆盖）。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # ---- 服务 ----
    app_name: str = "OA 智能体管理系统 MVP"
    api_prefix: str = "/api"
    environment: str = "development"
    ai_enabled: bool = True
    auth_provider: str = "mock"
    auth_tenant_id: str = 'local'
    auth_jwt_secret: str = ''
    auth_jwt_issuer: str = 'oa-local'
    auth_jwt_audience: str = 'oa-browser'
    auth_access_seconds: int = Field(default=7200, ge=60, le=7200)
    auth_refresh_days: int = Field(default=7, ge=1, le=7)
    auth_allowed_origins: list[str] = ['http://127.0.0.1:5182', 'http://localhost:5182']
    auth_cookie_secure: bool = True
    allow_test_database_reset: bool = False

    # ---- 数据库（PostgreSQL + pgvector，默认对接 docker-compose 的 5433 端口）----
    database_url: str = (
        "postgresql+asyncpg://oa:oa@localhost:5433/oa_agent"
    )
    database_sync_url: str = "postgresql+psycopg://oa:oa@localhost:5433/oa_agent"
    # LangGraph Checkpointer 使用的原生 psycopg 连接串（libpq 格式）
    checkpointer_url: str = "postgresql://oa:oa@localhost:5433/oa_agent"

    # ---- 向量维度（Mock 使用确定性向量，真实 ARK 以模型维度为准）----
    embedding_dim: int = 1536

    # Text generation and embeddings have independent provider settings.
    llm_provider: Literal["mock", "deepseek", "ark"] = "mock"
    llm_fallback_provider: Literal["none", "deepseek", "ark"] = "ark"
    llm_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    meeting_llm_timeout_seconds: float = Field(default=45.0, gt=0, le=60)
    embedding_provider: Literal["mock", "ark"] = "mock"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_chat_model: str = Field(default="deepseek-flash",
        validation_alias=AliasChoices("DEEPSEEK_CHAT_MODEL", "DEEPSEEK_MODEL"))
    # 火山方舟 ARK（OpenAI 兼容）
    ark_base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3",
        validation_alias=AliasChoices("ARK_BASE_URL", "DOUBAO_BASE_URL"))
    ark_api_key: str = Field(default="",
        validation_alias=AliasChoices("ARK_API_KEY", "DOUBAO_API_KEY"))
    ark_chat_model: str = Field(default="",
        validation_alias=AliasChoices("ARK_CHAT_MODEL", "DOUBAO_MODEL_NAME"))
    ark_thinking_type: Literal["default", "disabled", "enabled", "auto"] = "default"
    ark_embedding_model: str = Field(default="doubao-embedding-large",
        validation_alias=AliasChoices("ARK_EMBEDDING_MODEL", "EMBEDDING_MODEL"))
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=60)

    # ---- OA 提供方：mock | real ----
    oa_provider: str = "mock"
    oa_base_url: str = ""
    oa_api_key: str = ""
    oa_timeout_seconds: float = 10.0
    oa_read_retries: int = 2
    mock_state_file: str = "data/mock_state.json"

    # Private attachments. No scanner means PENDING, never an implicit pass.
    attachment_storage_dir: str = "data/leave_attachments"
    attachment_max_bytes: int = 10 * 1024 * 1024
    clamd_host: str = ""
    clamd_port: int = 3310
    attachment_scan_timeout_seconds: float = 10.0

    # Explicit opt-in transport; SMTP acceptance never means recipient delivery.
    smtp_enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = Field(default=587,ge=1,le=65535)
    smtp_from: str = ''
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(default=15,gt=0,le=60)
    notification_app_url: str = 'http://127.0.0.1:5195/oa/notifications'
    wecom_enabled: bool = False
    wecom_webhook_url: SecretStr = SecretStr('')
    wecom_tenant_id: str = ''
    wecom_department_id: str = ''
    wecom_timeout_seconds: float = Field(default=10, gt=0, le=30)

    # Knowledge source files.
    knowledge_storage_dir: str = "data/knowledge_files"

    # ---- 默认阈值（可被 agent_policy 覆盖）----
    intent_confidence_threshold: float = 0.6   # 意图置信度下限，低于则 unknown
    faq_answer_threshold: float = 0.25         # FAQ 检索/回答置信度下限（Mock 字符向量量级；ARK 建议 0.65+）
    nudge_after_seconds: int = 300             # 催办阈值（秒）
    escalate_after_seconds: int = 900          # 升级阈值（秒）
    scheduler_interval_seconds: int = 10       # 催办调度间隔（秒）

    # ---- 审计摘要保留（脱敏，不落敏感原文）----
    summary_max_len: int = 512
    audit_export_storage_dir: str = "data/audit_exports"
    audit_export_retention_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    """获取全局唯一配置实例（带缓存）。

    Returns:
        Settings: 应用配置实例。
    """
    return Settings()
