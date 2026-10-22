"""Authorization helpers for formal AI sources, policies and audit rows."""

from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.context import CurrentUser, get_policy_version, get_trace_id
from ..models.knowledge_source import KnowledgeSource
from ..models.knowledge_version import KnowledgeVersion
from ..models.oa_ai_scope import OABusinessAudit, OAKnowledgeBinding, OAAgentPolicy, OAAgentPolicyVersion
from .oa_access_service import user_department


def knowledge_binding_clause(actor):
    """Correlated binding filter, applied before ranking or limiting evidence."""
    return select(OAKnowledgeBinding.id).where(
        OAKnowledgeBinding.source_id == KnowledgeSource.id,
        OAKnowledgeBinding.tenant_id == actor.tenant_id,
        OAKnowledgeBinding.status == 'active',
        ((OAKnowledgeBinding.access_scope == 'tenant')
         | (OAKnowledgeBinding.owner_id == actor.user_id)
         | ((OAKnowledgeBinding.access_scope == 'department')
            & OAKnowledgeBinding.department_id.in_(actor.depts)))).exists()


async def source_allowed(session: AsyncSession, actor: CurrentUser, source_id, *, version_id=None) -> bool:
    """Return whether a formal source/version is visible to the current actor."""
    source = await session.scalar(select(KnowledgeSource).where(
        KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == actor.tenant_id).execution_options(populate_existing=True))
    if source is None:
        return False
    binding = await session.scalar(select(OAKnowledgeBinding).where(
        OAKnowledgeBinding.tenant_id == actor.tenant_id,
        OAKnowledgeBinding.source_id == source.id,
        OAKnowledgeBinding.status == "active").execution_options(populate_existing=True))
    if binding is None:
        return False
    if version_id is not None:
        version = await session.scalar(select(KnowledgeVersion).where(
            KnowledgeVersion.id == version_id, KnowledgeVersion.source_id == source.id,
            KnowledgeVersion.status == "published").execution_options(populate_existing=True))
        if version is None:
            return False
    department = await user_department(session, actor.tenant_id, actor.user_id)
    if binding.access_scope == "tenant":
        return True
    if binding.owner_id == actor.user_id:
        return True
    return binding.access_scope == "department" and binding.department_id is not None and binding.department_id == department


async def create_binding(session: AsyncSession, *, actor: CurrentUser, source_id, owner_id: str,
                         department_id: str | None, access_scope: str = "owner", version_rule: dict | None = None):
    if access_scope not in {"owner", "department", "tenant"}:
        raise ValueError("invalid knowledge access scope")
    source = await session.scalar(select(KnowledgeSource).where(
        KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == actor.tenant_id))
    if source is None:
        raise ValueError("knowledge source not found in tenant")
    binding = await session.scalar(select(OAKnowledgeBinding).where(
        OAKnowledgeBinding.tenant_id == actor.tenant_id, OAKnowledgeBinding.source_id == source.id))
    if binding is None:
        binding = OAKnowledgeBinding(tenant_id=actor.tenant_id, source_id=source.id,
            owner_id=owner_id, department_id=department_id, access_scope=access_scope,
            version_rule=version_rule or {}, status="active")
        session.add(binding)
    else:
        binding.owner_id = owner_id
        binding.department_id = department_id
        binding.access_scope = access_scope
        binding.version_rule = version_rule or binding.version_rule or {}
        binding.status = "active"
    await session.flush()
    return binding


async def record_audit(session: AsyncSession, *, actor: CurrentUser, resource: str, action: str,
                       object_type: str | None = None, object_id: str | None = None,
                       source_type: str | None = None, source_id: str | None = None,
                       result: str = "success", detail: dict | None = None):
    row = OABusinessAudit(tenant_id=actor.tenant_id, actor_id=actor.user_id,
        department_id=await user_department(session, actor.tenant_id, actor.user_id),
        resource=resource, action=action, object_type=object_type, object_id=object_id,
        source_type=source_type, source_id=source_id, trace_id=get_trace_id() or None,
        policy_version=get_policy_version() or None, result=result, detail=detail or {})
    session.add(row)
    await session.flush()
    return row


async def visible_audits(session: AsyncSession, *, actor: CurrentUser, resource: str | None = None,
                         trace_id=None, thread_id=None, business_id=None, actor_id=None, action=None,
                         start_time=None, end_time=None):
    """Refresh explicit audit authority before selecting own or department rows."""
    from .authorization_service import require_fresh_identity, require_permission
    from .oa_access_service import department_permission
    actor = await require_fresh_identity(actor, session=session)
    require_permission(actor, 'audit', 'read')
    department = await user_department(session, actor.tenant_id, actor.user_id)
    stmt = select(OABusinessAudit).where(OABusinessAudit.tenant_id == actor.tenant_id)
    if resource:
        stmt = stmt.where(OABusinessAudit.resource == resource)
    for column, value in ((OABusinessAudit.trace_id, trace_id), (OABusinessAudit.actor_id, actor_id),
                          (OABusinessAudit.action, action)):
        if value is not None:
            stmt = stmt.where(column == value)
    if business_id is not None:
        stmt = stmt.where((OABusinessAudit.object_id == business_id) | (OABusinessAudit.source_id == business_id))
    if start_time is not None:
        stmt = stmt.where(OABusinessAudit.created_at >= start_time)
    if end_time is not None:
        stmt = stmt.where(OABusinessAudit.created_at <= end_time)
    scope = OABusinessAudit.actor_id == actor.user_id
    if department is not None and department_permission(actor, 'audit', 'read'):
        scope = scope | (OABusinessAudit.department_id == department)
    stmt = stmt.where(scope)
    rows = (await session.scalars(stmt.order_by(OABusinessAudit.created_at.desc(), OABusinessAudit.id.desc())
        .execution_options(populate_existing=True))).all()
    from .oa_audit_access import audit_allowed
    return [row for row in rows if (thread_id is None or (row.detail or {}).get('thread_id') == str(thread_id))
        and await audit_allowed(session, actor, row)]


async def formal_policy(session: AsyncSession, *, actor: CurrentUser, scene: str):
    """Resolve immutable formal policy in most-specific order."""
    department = actor.depts[0] if actor.depts else await user_department(session, actor.tenant_id, actor.user_id)
    candidates = [("user", actor.user_id), ("department", department), ("tenant", actor.tenant_id)]
    for scope_type, value in candidates:
        policy = await session.scalar(select(OAAgentPolicy).where(
            OAAgentPolicy.tenant_id == actor.tenant_id, OAAgentPolicy.scene == scene,
            OAAgentPolicy.scope_type == scope_type, OAAgentPolicy.scope_value == value,
            OAAgentPolicy.status == "active").execution_options(populate_existing=True))
        if policy:
            version = await session.scalar(select(OAAgentPolicyVersion).where(
                OAAgentPolicyVersion.tenant_id == actor.tenant_id, OAAgentPolicyVersion.policy_id == policy.id,
                OAAgentPolicyVersion.status == "published").order_by(OAAgentPolicyVersion.version.desc())
                .execution_options(populate_existing=True))
            if version is not None:
                return FormalPolicy(policy=policy, version=version)
    return None


@dataclass(frozen=True)
class FormalPolicy:
    policy: OAAgentPolicy
    version: OAAgentPolicyVersion

    @property
    def enabled(self) -> bool:
        return bool(self.policy.enabled)

    @property
    def status(self) -> str:
        return self.version.status

    @property
    def thresholds(self) -> dict:
        return self.version.thresholds or {}

    @property
    def rule_version(self) -> str:
        return self.version.rule_version

    @property
    def version_number(self) -> int:
        return self.version.version


async def list_formal_policies(session: AsyncSession, *, tenant_id: str, scene: str | None = None):
    stmt = select(OAAgentPolicy).where(OAAgentPolicy.tenant_id == tenant_id)
    if scene:
        stmt = stmt.where(OAAgentPolicy.scene == scene)
    return list((await session.execute(stmt.order_by(OAAgentPolicy.scene, OAAgentPolicy.scope_type))).scalars().all())


async def list_formal_versions(session: AsyncSession, *, tenant_id: str, scene: str | None = None):
    stmt = select(OAAgentPolicyVersion, OAAgentPolicy).join(
        OAAgentPolicy, OAAgentPolicy.id == OAAgentPolicyVersion.policy_id
    ).where(OAAgentPolicyVersion.tenant_id == tenant_id)
    if scene:
        stmt = stmt.where(OAAgentPolicy.scene == scene)
    return list((await session.execute(stmt.order_by(OAAgentPolicy.scene, OAAgentPolicyVersion.version.desc()))).all())


async def upsert_formal_policy(session: AsyncSession, *, actor: CurrentUser, scene: str,
                               scope_type: str, scope_value: str | None, enabled: bool,
                               thresholds: dict, rule_version: str):
    if scope_type == "global":
        scope_type = "tenant"
    if scope_type not in {"tenant", "department", "user"}:
        raise ValueError("正式策略范围必须是 tenant、department 或 user")
    if scope_type == "tenant":
        scope_value = actor.tenant_id
    elif not scope_value:
        raise ValueError("部门或用户策略必须提供 scope_value")
    policy = await session.scalar(select(OAAgentPolicy).where(
        OAAgentPolicy.tenant_id == actor.tenant_id, OAAgentPolicy.scene == scene,
        OAAgentPolicy.scope_type == scope_type, OAAgentPolicy.scope_value == scope_value))
    if policy is None:
        policy = OAAgentPolicy(tenant_id=actor.tenant_id, scene=scene, scope_type=scope_type,
                               scope_value=scope_value, department_id=scope_value if scope_type == "department" else None,
                               enabled=enabled, status="active")
        session.add(policy)
        await session.flush()
    else:
        policy.enabled = enabled
        policy.status = "active"
    versions = (await session.scalars(select(OAAgentPolicyVersion.version).where(
        OAAgentPolicyVersion.tenant_id == actor.tenant_id, OAAgentPolicyVersion.policy_id == policy.id))).all()
    await session.execute(update(OAAgentPolicyVersion).where(
        OAAgentPolicyVersion.tenant_id == actor.tenant_id, OAAgentPolicyVersion.policy_id == policy.id,
        OAAgentPolicyVersion.status == "published").values(status="offline"))
    version = OAAgentPolicyVersion(tenant_id=actor.tenant_id, policy_id=policy.id,
        version=max(versions, default=0) + 1, thresholds=thresholds or {}, rule_version=rule_version,
        status="published", created_by=actor.user_id, published_at=datetime.now(timezone.utc))
    session.add(version)
    await session.flush()
    return policy, version
