"""
OA 智能体管理系统 - 应用配置模块。

使用 pydantic-settings 读取环境变量（.env），集中管理数据库连接、模型提供方、OA 提供方、
开关阈值等运行参数。所有配置项均有默认值，保证 MVP 可开箱即用（Mock + Docker PG）。
"""

from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
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
    clamd_port: int = Field(default=3310, ge=1, le=65535)
    attachment_scan_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # Explicit opt-in transport; SMTP acceptance never means recipient delivery.
    smtp_enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = Field(default=587,ge=1,le=65535)
    smtp_from: str = ''
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(default=15,gt=0,le=60)
    # One shared mailbox, explicitly provisioned for one tenant. Credentials are server-only.
    public_mailbox_enabled: bool = False
    public_mailbox_name: str = '综合办公公共邮箱'
    imap_host: str = ''
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_username: str = ''
    imap_password: SecretStr = SecretStr('')
    imap_timeout_seconds: float = Field(default=20, gt=0, le=60)
    notification_app_url: str = 'http://127.0.0.1:5195/oa/notifications'
    wecom_enabled: bool = False
    wecom_webhook_url: SecretStr = SecretStr('')
    wecom_tenant_id: str = ''
    wecom_department_id: str = ''
    wecom_timeout_seconds: float = Field(default=10, gt=0, le=30)
    wecom_policy_activated_at: datetime | None = None
    wecom_group_interval_seconds: int = Field(default=60, ge=0, le=3600)
    wecom_nudge_interval_seconds: int = Field(default=7200, ge=7200, le=86400)
    notification_wecom_worker_enabled: bool = False
    notification_smtp_worker_enabled: bool = False
    business_scheduler_enabled: bool = True

    @field_validator('wecom_policy_activated_at')
    @classmethod
    def aware_wecom_cutover(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError('企业微信启用时间必须包含时区')
        return value

    # TUIRoomKit credentials stay server-side; only short-lived member UserSigs leave the API.
    trtc_sdk_app_id: int = Field(default=0, ge=0, le=4294967295)
    trtc_sdk_secret_key: SecretStr = SecretStr('')
    trtc_user_sig_expire_seconds: int = Field(default=3600, ge=60, le=3600)
    trtc_admin_user_id: str = Field(default='administrator', min_length=1, max_length=32)
    meeting_transcription_enabled: bool = False
    meeting_transcription_secret_id: SecretStr = SecretStr('')
    meeting_transcription_secret_key: SecretStr = SecretStr('')
    meeting_transcription_callback_key: SecretStr = SecretStr('')
    meeting_transcription_callback_url: str = ''
    meeting_transcription_region: str = 'ap-guangzhou'
    meeting_transcription_language: str = 'bigmodel-zh'
    meeting_transcription_retention_days: int = Field(default=30, ge=1, le=365)

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

    # Independent watchdog; outbound alerts require a separate explicit opt-in.
    ops_state_dir: str = 'data/operations-monitor'
    ops_health_url: str = 'http://127.0.0.1:8015/healthz'
    ops_poll_seconds: int = Field(default=60, ge=10, le=60)
    ops_probe_timeout_seconds: float = Field(default=10, gt=0, le=15)
    ops_backlog_age_seconds: int = Field(default=120, ge=30, le=180)
    ops_backup_max_age_hours: int = Field(default=25, ge=1, le=168)
    ops_backup_max_runtime_seconds: int = Field(default=3600, ge=60, le=86400)
    ops_model_probes_enabled: bool = False
    ops_alert_delivery_enabled: bool = False
    ops_alert_email_to: str = ''
    ops_log_files: list[str] = Field(default_factory=list, max_length=8)
    ops_log_keywords: list[str] = Field(default_factory=lambda: ['ERROR', 'CRITICAL', 'Traceback'],
                                      min_length=1, max_length=16)

    @field_validator('ops_log_files')
    @classmethod
    def validate_log_files(cls, values):
        if any(not value or len(value) > 4096 or '\x00' in value or not Path(value).is_absolute()
               for value in values):
            raise ValueError('Log files require absolute paths')
        return values

    @field_validator('ops_log_keywords')
    @classmethod
    def validate_log_keywords(cls, values):
        if any(not value.strip() or len(value) > 128 or '\x00' in value for value in values):
            raise ValueError('Log keywords must contain 1 to 128 characters')
        return values


@lru_cache
def get_settings() -> Settings:
    """获取全局唯一配置实例（带缓存）。

    Returns:
        Settings: 应用配置实例。
    """
    return Settings()
