"""Live identity and canonical evidence for formal graph runs and cached answers."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from ..core.context import get_current_user
from ..core.errors import AppException, ErrorCode
from ..models.agent_thread import AgentThread
from ..models.knowledge_chunk import KnowledgeChunk
from ..models.knowledge_source import KnowledgeSource
from ..models.knowledge_version import KnowledgeVersion
from .authorization_service import require_fresh_identity, require_permission
from .oa_scope_service import source_allowed


def unavailable_source():
    return AppException(ErrorCode.FORBIDDEN, '引用知识已失效或权限已变化，请重新提问', http_status=403)


async def actor_for_thread(db, state):
    actor = await require_fresh_identity(get_current_user(), session=db)
    if actor.data_scope.get('identity_provider') != 'builtin' or (
        state.get('user_id') != actor.user_id or state.get('tenant_id') != actor.tenant_id
    ):
        raise unavailable_source()
    try:
        identifier = UUID(str(state.get('thread_id')))
    except ValueError:
        raise unavailable_source() from None
    thread = await db.scalar(select(AgentThread).where(AgentThread.id == identifier,
        AgentThread.tenant_id == actor.tenant_id, AgentThread.user_id == actor.user_id,
        AgentThread.scene == state.get('scene')))
    if thread is None:
        raise unavailable_source()
    if thread.scene not in {'faq', 'ticket', 'leave'}:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, '此智能场景尚未接通正式业务', http_status=503)
    require_permission(actor, 'knowledge' if thread.scene == 'faq' else thread.scene, 'read')
    return actor


async def faq_context(db, state, *, tool='search_knowledge'):
    return await scene_context(db, state, tool=tool)


async def scene_context(db, state, *, tool='get_user_context'):
    from . import policy_service
    from .authorization_service import authorize_tool
    actor = await actor_for_thread(db, state)
    department = actor.depts[0] if actor.depts else ''
    scene = state['scene']
    if not await policy_service.is_scene_enabled(db, scene, actor.user_id, department, actor.tenant_id):
        raise AppException(ErrorCode.DEGRADED, '当前场景智能路径已关闭，请转人工处理', http_status=503)
    thresholds = await policy_service.get_thresholds(db, scene, user_id=actor.user_id,
        dept_id=department, tenant_id=actor.tenant_id)
    await authorize_tool(actor, scene, tool, session=db, policy_tools=thresholds.get('allowed_tools'))
    return actor, thresholds


async def canonical_chunks(db, actor, chunks):
    require_permission(actor, 'knowledge', 'read')
    result = []
    now = datetime.now(timezone.utc)
    for item in chunks:
        try:
            chunk_id, version_id, source_id = (UUID(item[key]) for key in ('chunk_id', 'version_id', 'source_id'))
        except (KeyError, ValueError, TypeError):
            raise unavailable_source() from None
        row = (await db.execute(select(KnowledgeChunk, KnowledgeVersion, KnowledgeSource)
            .join(KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id)
            .join(KnowledgeSource, KnowledgeVersion.source_id == KnowledgeSource.id)
            .where(KnowledgeChunk.id == chunk_id, KnowledgeVersion.id == version_id,
                KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == actor.tenant_id,
                KnowledgeVersion.status == 'published', KnowledgeVersion.parse_status == 'READY',
                (KnowledgeVersion.effective_at.is_(None)) | (KnowledgeVersion.effective_at <= now),
                (KnowledgeVersion.expire_at.is_(None)) | (KnowledgeVersion.expire_at > now),
                (KnowledgeVersion.permission_tags == []) | KnowledgeVersion.permission_tags.overlap(actor.depts))
            .execution_options(populate_existing=True))).one_or_none()
        if row is None or not await source_allowed(db, actor, source_id, version_id=version_id):
            raise unavailable_source()
        chunk, version, source = row
        digest = sha256(chunk.content.encode()).hexdigest()
        if item.get('content_hash') and item['content_hash'] != digest:
            raise unavailable_source()
        result.append(dict(chunk_id=str(chunk.id), version_id=str(version.id), source_id=str(source.id),
            document_id=str(source.id), version=version.version, title=source.name,
            content=chunk.content, content_hash=digest, source_location=chunk.source_location or '',
            similarity=float(item.get('similarity', 0))))
    return result


async def validate_cached_answer(db, actor, answer):
    actor = await require_fresh_identity(actor, session=db)
    sources = answer.get('sources') if isinstance(answer, dict) else None
    if not sources or any(not item.get('content_hash') for item in sources):
        raise unavailable_source()
    from . import policy_service
    from .authorization_service import authorize_tool
    department = actor.depts[0] if actor.depts else ''
    if not await policy_service.is_scene_enabled(db, 'faq', actor.user_id, department, actor.tenant_id):
        raise unavailable_source()
    thresholds = await policy_service.get_thresholds(db, 'faq', user_id=actor.user_id,
        dept_id=department, tenant_id=actor.tenant_id)
    for tool in ('get_user_context', 'search_knowledge'):
        await authorize_tool(actor, 'faq', tool, session=db, policy_tools=thresholds.get('allowed_tools'))
    try:
        confidence = float(sources[0].get('similarity', 0))
        threshold = float(thresholds.get('faq_answer', 0.65))
    except (TypeError, ValueError):
        raise unavailable_source() from None
    if not 0 <= confidence <= 1 or confidence < threshold:
        raise unavailable_source()
    await canonical_chunks(db, actor, sources)
