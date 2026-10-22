"""
OA 智能体管理系统 - 知识库管理接口路由。

提供文档导入、状态管理与列表（管理员/知识运营）：
    GET  /api/admin/knowledge
    POST /api/admin/knowledge
    PUT  /api/admin/knowledge/{id}/status
"""

from uuid import UUID

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.enums import AuditAction
from ...db.session import get_db
from ...repositories import knowledge_repo
from ...schemas.common import ok
from ...schemas.knowledge import (
    KnowledgeDocumentOut,
    KnowledgeImportRequest,
    KnowledgeStatusRequest,
)
from ...schemas.knowledge_version import KnowledgePreviewResponse
from ...schemas.knowledge_version import KnowledgeVersionCreateRequest, KnowledgeVersionOut
from ...services.document_parser import DocumentParseError
from ...storage.local import LocalObjectStore
from ...core.config import get_settings
from ...services import audit_service, knowledge_service
from ...services import knowledge_version_service
from ..deps import require_roles

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])
_settings = get_settings()


@router.get("")
async def list_documents(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    """列出知识文档。

    Args:
        session: 数据库会话。
        user: 当前用户（admin）。

    Returns:
        ApiResponse: 文档列表。
    """
    docs = await knowledge_repo.list_documents(session)
    return ok([_to_out(d).model_dump() for d in docs])


@router.post("")
async def import_document(
    payload: KnowledgeImportRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    """导入知识文档（切分 + 向量化 + 入库）。

    Args:
        payload: 文档导入请求。
        session: 数据库会话。
        user: 当前用户（admin）。

    Returns:
        ApiResponse: 导入结果。
    """
    result = await knowledge_service.import_document(
        session,
        title=payload.title,
        content=payload.content,
        format=payload.format,
        permission_tags=payload.permission_tags,
        owner_id=payload.owner_id,
        effective_at=payload.effective_at,
        expire_at=payload.expire_at,
    )
    await audit_service.audit(
        session,
        AuditAction.POLICY_CHANGED.value,
        actor_id=user.user_id,
        target_type="knowledge",
        target_id=str(result.get("document_id", "")),
        input_summary={"title": payload.title},
    )
    await session.commit()
    return ok(result)


@router.post("/preview", response_model=None)
async def preview_file(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    """Parse and privately persist a knowledge source for preview."""
    from ...services.knowledge_service import preview_document

    filename = file.filename or ""
    content = await file.read()
    try:
        preview = preview_document(
            content, filename, store=LocalObjectStore(_settings.knowledge_storage_dir)
        )
    except DocumentParseError as exc:
        from ...core.errors import AppException
        from ...core.enums import ErrorCode

        raise AppException(
            ErrorCode.BAD_REQUEST,
            "知识文件解析失败",
            detail={"code": exc.code},
        ) from exc
    return ok(KnowledgePreviewResponse.model_validate(preview).model_dump())


@router.post("/versions")
async def create_version(
    payload: KnowledgeVersionCreateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    from ...core.enums import ErrorCode
    from ...core.errors import AppException

    try:
        version = await knowledge_version_service.create_version(
            session, source_name=payload.source_name, content=payload.content.encode("utf-8"),
            filename=payload.filename, permission_tags=payload.permission_tags,
            owner_id=payload.owner_id, effective_at=payload.effective_at, expire_at=payload.expire_at,
            store=LocalObjectStore(_settings.knowledge_storage_dir),
            tenant_id=user.tenant_id,
        )
        if get_settings().oa_provider == "builtin":
            from ...services.oa_scope_service import create_binding
            from ...services.oa_access_service import user_department
            await create_binding(session, actor=user, source_id=version.source_id,
                owner_id=user.user_id, department_id=await user_department(session, user.tenant_id, user.user_id),
                access_scope="department")
    except (ValueError, DocumentParseError) as exc:
        raise AppException(ErrorCode.BAD_REQUEST, "知识版本创建失败", detail={"reason": str(exc)}) from exc
    await session.commit()
    return ok(_version_out(version).model_dump())


@router.post("/versions/{version_id}/publish")
async def publish_version(
    version_id: UUID,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    from ...core.enums import ErrorCode
    from ...core.errors import AppException

    try:
        version = await knowledge_version_service.publish_version(session, version_id)
    except ValueError as exc:
        raise AppException(ErrorCode.BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ok(_version_out(version).model_dump())


@router.post("/versions/upload")
async def upload_version(
    source_name: str = Form(...),
    file: UploadFile = File(...),
    permission_tags: str = Form(""),
    owner_id: str = Form("u_admin_001"),
    effective_at: str | None = Form(None),
    expire_at: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    from ...core.enums import ErrorCode
    from ...core.errors import AppException

    def parse_dt(value: str | None):
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    try:
        version = await knowledge_version_service.create_version(
            session, source_name=source_name, content=await file.read(),
            filename=file.filename or "", permission_tags=[tag for tag in permission_tags.split(",") if tag],
            owner_id=owner_id, effective_at=parse_dt(effective_at), expire_at=parse_dt(expire_at),
            store=LocalObjectStore(_settings.knowledge_storage_dir), content_type=file.content_type,
            tenant_id=user.tenant_id,
        )
        if get_settings().oa_provider == "builtin":
            from ...services.oa_scope_service import create_binding
            from ...services.oa_access_service import user_department
            await create_binding(session, actor=user, source_id=version.source_id,
                owner_id=user.user_id, department_id=await user_department(session, user.tenant_id, user.user_id),
                access_scope="department")
    except (ValueError, DocumentParseError) as exc:
        raise AppException(ErrorCode.BAD_REQUEST, "知识文件导入失败", detail={"reason": str(exc)}) from exc
    await session.commit()
    return ok(_version_out(version).model_dump())


@router.put("/{document_id}/status")
async def update_status(
    document_id: UUID,
    payload: KnowledgeStatusRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    """下线/更新文档状态。

    Args:
        document_id: 文档 ID。
        payload: 状态变更请求。
        session: 数据库会话。
        user: 当前用户（admin）。

    Returns:
        ApiResponse: 更新后的文档。
    """
    from ...core.errors import not_found

    doc = await knowledge_repo.get_document(session, document_id)
    if doc is None:
        raise not_found("文档不存在")
    doc.status = payload.status
    await audit_service.audit(
        session,
        AuditAction.POLICY_CHANGED.value,
        actor_id=user.user_id,
        target_type="knowledge",
        target_id=str(document_id),
        input_summary={"status": payload.status},
    )
    await session.commit()
    return ok(_to_out(doc).model_dump())


def _to_out(d) -> KnowledgeDocumentOut:
    """ORM -> DTO。

    Args:
        d: 文档 ORM 对象。

    Returns:
        KnowledgeDocumentOut: DTO。
    """
    return KnowledgeDocumentOut(
        id=str(d.id),
        title=d.title,
        version=d.version,
        status=d.status,
        format=d.format,
        permission_tags=d.permission_tags or [],
        effective_at=d.effective_at,
        expire_at=d.expire_at,
        owner_id=d.owner_id,
        created_at=d.created_at,
    )


def _version_out(version) -> KnowledgeVersionOut:
    return KnowledgeVersionOut(
        id=str(version.id), source_id=str(version.source_id), version=version.version,
        status=version.status, parse_status=version.parse_status,
        content_hash=version.content_hash, permission_tags=version.permission_tags or [],
        effective_at=version.effective_at, expire_at=version.expire_at,
    )
