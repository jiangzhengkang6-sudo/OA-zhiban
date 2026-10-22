"""Private leave files with resource authorization and verified references."""
import asyncio
import hashlib
import io
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select

from ..core.config import get_settings
from ..core.errors import AppException, ErrorCode
from ..models.leave_application import LeaveApplication
from ..models.leave_attachment import LeaveAttachment
from ..models.agent_thread import AgentThread
from ..providers import file_scanner
from . import audit_service


def metadata(row):
    return {'attachment_id': str(row.id), 'filename': row.filename,
            'content_type': row.content_type, 'size_bytes': row.size_bytes,
            'sha256': row.sha256, 'scan_status': row.scan_status}


async def application_scope(db, actor, application_id, *, write=False):
    query = select(LeaveApplication).where(LeaveApplication.id == application_id)
    if write:
        query = query.with_for_update()
    application = (await db.scalars(query)).one_or_none()
    if application is None:
        raise AppException(ErrorCode.NOT_FOUND, '请假申请不存在', http_status=404)
    permitted = application.tenant_id == actor.tenant_id and application.user_id == actor.user_id
    if not permitted and not write and application.thread_id:
        from .task_service import can_view_task
        thread = await db.get(AgentThread, application.thread_id)
        permitted = thread is not None and await can_view_task(db, thread, actor)
    if not permitted:
        raise AppException(ErrorCode.FORBIDDEN, '无权访问该申请附件', http_status=403)
    if write and application.status not in {'DRAFT', 'NEEDS_FIX', 'REJECTED', 'PAUSED'}:
        raise AppException(ErrorCode.INVALID_STATE, '当前申请不可修改附件', http_status=409)
    if write and application.status == 'PAUSED':
        from .leave_application_service import _validate_precheck_retry
        await _validate_precheck_retry(db, application)
    return application


async def resolve_refs(db, application_id, refs):
    try:
        ids = [UUID(ref) for ref in refs]
    except (ValueError, TypeError, AttributeError):
        raise AppException(ErrorCode.BAD_REQUEST, '附件必须使用真实上传后的引用', http_status=400) from None
    rows = (await db.scalars(select(LeaveAttachment).where(
        LeaveAttachment.application_id == application_id, LeaveAttachment.id.in_(ids)))).all() if ids else []
    by_id = {row.id: row for row in rows}
    if any(item not in by_id for item in ids):
        raise AppException(ErrorCode.BAD_REQUEST, '附件引用不属于当前申请', http_status=400)
    return [by_id[item] for item in ids]


def storage_path(row):
    root = Path(get_settings().attachment_storage_dir).resolve()
    path = (root / row.storage_ref).resolve()
    if path.parent != root:
        raise AppException(ErrorCode.INVALID_STATE, '附件存储引用无效', http_status=409)
    return path


def _read_verified(row):
    content = storage_path(row).read_bytes()
    if len(content) != row.size_bytes or hashlib.sha256(content).hexdigest() != row.sha256:
        raise OSError('attachment integrity check failed')
    return content


def _validate_content(filename, mime, content):
    suffix = Path(filename).suffix.lower()
    allowed = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
    expected = allowed.get(suffix)
    if not expected or mime != expected or not content:
        raise ValueError('extension/content type mismatch')
    if suffix == '.pdf':
        if not content.startswith(b'%PDF-'):
            raise ValueError('not PDF')
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not 0 < len(reader.pages) <= 100:
            raise ValueError('unsupported PDF')
    else:
        with Image.open(io.BytesIO(content)) as picture:
            if picture.format != ('PNG' if suffix == '.png' else 'JPEG'):
                raise ValueError('image type mismatch')
            if picture.width * picture.height > 25_000_000:
                raise ValueError('image too large')
            picture.verify()
    return expected


async def upload(db, actor, application_id, file):
    application = await application_scope(db, actor, application_id, write=True)
    content = await file.read(get_settings().attachment_max_bytes + 1)
    if len(content) > get_settings().attachment_max_bytes:
        raise AppException(ErrorCode.BAD_REQUEST, '附件超过大小上限（默认 10 MB）', http_status=413)
    filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    if not filename or len(filename) > 256 or any(ord(c) < 32 for c in filename):
        raise AppException(ErrorCode.BAD_REQUEST, '附件名称无效', http_status=400)
    try:
        mime = await asyncio.to_thread(_validate_content, filename, file.content_type, content)
    except Exception:
        raise AppException(ErrorCode.BAD_REQUEST, '仅支持内容有效的 PDF、PNG、JPEG 文件', http_status=400) from None
    digest = hashlib.sha256(content).hexdigest()
    row = (await db.scalars(select(LeaveAttachment).where(
        LeaveAttachment.application_id == application.id, LeaveAttachment.sha256 == digest,
        LeaveAttachment.filename == filename))).first()
    if row is None:
        row = LeaveAttachment(id=uuid4(), application_id=application.id, filename=filename,
                              storage_ref=uuid4().hex, sha256=digest, size_bytes=len(content),
                              content_type=mime, scan_status=await file_scanner.scan_bytes(content))
        path = storage_path(row)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)
        db.add(row)
        await db.flush()
    refs = list(dict.fromkeys([*(application.latest_fields.get('attachments') or []), str(row.id)]))
    application.latest_fields = {**application.latest_fields, 'attachments': refs}
    await audit_service.audit(db, 'leave_attachment_upload', actor_id=actor.user_id,
        business_id=application.business_id, target_type='leave_attachment', target_id=str(row.id),
        output_summary={'scan_status': row.scan_status, 'size_bytes': row.size_bytes})
    return metadata(row)


async def list_attachments(db, actor, application_id):
    application = await application_scope(db, actor, application_id)
    rows = await resolve_refs(db, application.id, application.latest_fields.get('attachments') or [])
    return [metadata(row) for row in rows]


async def download(db, actor, application_id, attachment_id):
    application = await application_scope(db, actor, application_id)
    row = (await resolve_refs(db, application.id, [str(attachment_id)]))[0]
    if row.scan_status != 'CLEAN':
        raise AppException(ErrorCode.INVALID_STATE, '附件尚未通过安全扫描，禁止下载', http_status=409)
    try:
        content = await asyncio.to_thread(_read_verified, row)
    except OSError:
        raise AppException(ErrorCode.INVALID_STATE, '附件缺失或完整性校验失败', http_status=409) from None
    await audit_service.audit(db, 'leave_attachment_download', actor_id=actor.user_id,
        business_id=application.business_id, target_type='leave_attachment', target_id=str(row.id))
    return row, content


async def rescan(db, actor, application_id, attachment_id):
    application = await application_scope(db, actor, application_id, write=True)
    row = (await resolve_refs(db, application.id, [str(attachment_id)]))[0]
    try:
        content = await asyncio.to_thread(_read_verified, row)
        row.scan_status = await file_scanner.scan_bytes(content)
    except OSError:
        row.scan_status = 'ERROR'
    await audit_service.audit(db, 'leave_attachment_scan', actor_id=actor.user_id,
        business_id=application.business_id, target_type='leave_attachment', target_id=str(row.id),
        output_summary={'scan_status': row.scan_status})
    return metadata(row)


async def precheck(db, application_id, refs, required):
    try:
        rows = await resolve_refs(db, application_id, refs)
        valid = bool(rows) if required else True
        for row in rows:
            if row.scan_status != 'CLEAN' or not row.sha256:
                valid = False
                continue
            await asyncio.to_thread(_read_verified, row)
    except (AppException, OSError):
        valid = False
    return {'item': 'attachment', 'result': 'pass' if valid else 'fail',
            'reason': '附件引用、扫描及完整性已验证' if valid else '附件缺失、未通过扫描或引用无效',
            'suggestion': '' if valid else '上传有效证明；待扫描服务可用后重新扫描并提交'}
