"""Frozen MVP schema; adopt existing compatible tables without rewriting data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Immutable migration snapshot. Never import evolving application models here.
def baseline_metadata():
    metadata = sa.MetaData(naming_convention={"pk": "pk_%(table_name)s", "uq": "uq_%(table_name)s_%(column_0_name)s"})
    def column(name, kind, nullable=True):
        return sa.Column(name, kind, nullable=nullable)
    def table(name, columns, constraints=(), serial=False):
        return sa.Table(name, metadata, *columns,
            sa.Column("id", sa.BigInteger() if serial else pg.UUID(), primary_key=True, autoincrement=serial),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            *constraints)
    s, j, u, dt = sa.String, pg.JSONB, pg.UUID, sa.DateTime
    thread = table("agent_thread", [
        column("user_id", s(64), False), column("tenant_id", s(64), False), column("scene", s(16), False),
        column("status", s(32), False), column("intent", s(16)), column("business_id", s(64)),
        column("current_interrupt_id", s(64)), column("waiting_since", dt(timezone=True)),
        column("last_nudge_at", dt(timezone=True)), column("escalated_at", dt(timezone=True)),
        column("policy_version", s(32)), column("error_code", s(16)), column("error_msg", sa.Text())])
    message = table("agent_message", [column("thread_id", u(), False), column("seq", sa.Integer(), False),
        column("role", s(16), False), column("content_summary", sa.Text()), column("content_hash", s(64)), column("full_content", j())])
    precheck = table("precheck_result", [column("thread_id", u(), False), column("business_id", s(64)),
        column("rule_version", s(32)), column("item", s(32), False), column("result", s(8), False),
        column("reason", sa.Text()), column("evidence", j()), column("suggestion", sa.Text())])
    decision = table("human_decision", [column("thread_id", u(), False), column("interrupt_id", s(64)),
        column("actor_id", s(64), False), column("action", s(16), False), column("comment", sa.Text()),
        column("edited_data", j()), column("payload_hash", s(64))])
    ticket = table("ticket_context", [column("ticket_id", s(64), False), column("thread_id", u(), False),
        column("category", s(32)), column("priority", s(16)), column("impact", s(32)), column("summary", sa.Text()),
        column("extracted_fields", j()), column("status", s(16), False), column("queue_id", s(32)),
        column("assignee_id", s(64)), column("merged_from", j()), column("feedback", s(16)), column("last_updated_at", dt())],
        [sa.UniqueConstraint("ticket_id")])
    document = table("knowledge_document", [column("title", s(255), False), column("version", sa.Integer(), False),
        column("status", s(16), False), column("format", s(16), False), column("permission_tags", pg.ARRAY(s(32)), False),
        column("effective_at", dt()), column("expire_at", dt()), column("owner_id", s(64)),
        column("content_hash", s(64)), column("source_path", sa.Text()), column("created_by", s(64))])
    chunk = table("knowledge_chunk", [column("document_id", u(), False), column("chunk_index", sa.Integer(), False),
        column("content", sa.Text(), False), column("content_hash", s(64)), column("embedding", Vector(1536)),
        column("source_location", s(128)), column("token_count", sa.Integer())])
    audit = table("audit_event", [column("trace_id", s(36)), column("thread_id", u()), column("business_id", s(64)),
        column("actor_id", s(64)), column("action", s(32), False), column("target_type", s(32)), column("target_id", s(64)),
        column("tool_name", s(64)), column("input_summary", j()), column("output_summary", j()),
        column("result", s(8)), column("error_code", s(16)), column("policy_version", s(32)), column("duration_ms", sa.Integer())], serial=True)
    table("agent_policy", [column("scene", s(16), False), column("scope_type", s(16), False), column("scope_value", s(64)),
        column("enabled", sa.Boolean(), False), column("thresholds", j()), column("rule_version", s(32), False),
        column("updated_by", s(64)), column("effective_at", dt())],
        [sa.UniqueConstraint("scene", "scope_type", "scope_value", "rule_version", name="uq_agent_policy_scene_scope_version")])
    for name, obj, fields in [
        ("ix_agent_thread_user_id", thread, ["user_id"]), ("ix_agent_thread_user_created", thread, ["user_id", "created_at"]),
        ("ix_agent_thread_status_waiting", thread, ["status", "waiting_since"]), ("ix_agent_thread_business", thread, ["business_id"]),
        ("ix_agent_message_thread_seq", message, ["thread_id", "seq"]),
        ("ix_precheck_business_version", precheck, ["business_id", "rule_version"]), ("ix_precheck_thread", precheck, ["thread_id"]),
        ("ix_human_decision_thread", decision, ["thread_id"]), ("ix_human_decision_actor_id", decision, ["actor_id"]),
        ("ix_human_decision_actor_created", decision, ["actor_id", "created_at"]),
        ("ix_ticket_assignee_status", ticket, ["assignee_id", "status"]),
        ("ix_knowledge_doc_status", document, ["status", "effective_at", "expire_at"]),
        ("ix_knowledge_chunk_doc", chunk, ["document_id", "chunk_index"]),
        ("ix_audit_trace", audit, ["trace_id"]), ("ix_audit_thread", audit, ["thread_id"]),
        ("ix_audit_actor_created", audit, ["actor_id", "created_at"]), ("ix_audit_action", audit, ["action"]),
        ("ix_audit_business", audit, ["business_id"])]:
        sa.Index(name, *(obj.c[field] for field in fields))
    sa.Index("ix_knowledge_doc_permission", document.c.permission_tags, postgresql_using="gin")
    return metadata


def upgrade():
    connection = op.get_bind()
    connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
    metadata = baseline_metadata()
    schema = connection.execute(sa.text("SELECT current_schema()")).scalar_one()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names(schema=schema))
    for table in metadata.sorted_tables:
        if table.name not in existing:
            table.create(connection)
            continue
        columns = {col["name"]: col for col in inspector.get_columns(table.name, schema=schema)}
        for expected in table.columns:
            actual = columns.get(expected.name)
            if actual is None or str(actual["type"].compile(dialect=connection.dialect)) != str(expected.type.compile(dialect=connection.dialect)) or actual["nullable"] != expected.nullable:
                raise RuntimeError(f"已有 MVP 表结构不兼容：{table.name}.{expected.name}；请备份并检查，迁移未完成")
        if inspector.get_pk_constraint(table.name, schema=schema)["constrained_columns"] != ["id"]:
            raise RuntimeError(f"已有 MVP 主键不兼容：{table.name}")
        indexes = {idx["name"] for idx in inspector.get_indexes(table.name, schema=schema)}
        for index in table.indexes:
            if index.name not in indexes:
                index.create(connection)


def downgrade():
    raise RuntimeError("禁止删除 MVP 基线表；使用备份恢复，不清空已有数据")
