"""Private formal files: immutable bytes, explicit scanner state, scoped references."""
import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from ..core.config import get_settings
from ..models.oa_leave import OALeaveAttachment
from ..providers import file_scanner
from .oa_access_service import invalid, revision_conflict
from .oa_command_service import OACommand, CommandOutcome, run_command
from . import oa_leave_service as leaves
from .leave_attachment_service import _validate_content


def metadata(row):
    return dict(id=row.id,filename=row.filename,mime_type=row.mime_type,size=row.size,
        sha256=row.sha256,scan_status=row.scan_status)


def storage_path(row):
    root = (Path(get_settings().attachment_storage_dir)/'formal').resolve()
    path = (root/row.storage_key).resolve()
    if path.parent != root: raise invalid('附件存储引用无效')
    return path


def read_verified(row):
    content = storage_path(row).read_bytes()
    if len(content)!=row.size or hashlib.sha256(content).hexdigest()!=row.sha256: raise OSError('integrity')
    return content


async def refs(db,actor,leave_id,ids):
    rows = (await db.scalars(select(OALeaveAttachment).where(OALeaveAttachment.tenant_id==actor.tenant_id,
        OALeaveAttachment.leave_id==leave_id,OALeaveAttachment.id.in_(ids)))).all() if ids else []
    by_id = {row.id:row for row in rows}
    if any(key not in by_id for key in ids): raise invalid('附件引用不存在或不属于本申请')
    return [by_id[key] for key in ids]


async def preflight(db,actor,leave_id,ids):
    actor,_ = await leaves.applicant_access(db,actor,leave_id,write=True)
    rows = await refs(db,actor,leave_id,ids)
    for row in rows:
        if row.scan_status!='CLEAN': raise invalid('附件尚未通过安全扫描')
        try: await asyncio.to_thread(read_verified,row)
        except OSError: raise invalid('附件缺失或完整性校验失败') from None
    return [metadata(row) for row in rows]


async def verify_manifest(db,actor,leave_id,manifest):
    rows = await refs(db,actor,leave_id,[item['id'] for item in manifest])
    if [metadata(row) for row in rows] != manifest: raise revision_conflict()


async def upload(db,actor,leave_id,file,*,operation_id,expected_revision):
    actor,leave = await leaves.applicant_access(db,actor,leave_id,write=True)
    content = await file.read(get_settings().attachment_max_bytes+1)
    if not content or len(content)>get_settings().attachment_max_bytes: raise invalid('附件为空或超过大小上限')
    filename = (file.filename or '').replace('\\','/').rsplit('/',1)[-1]
    if not filename or len(filename)>255 or any(ord(c)<32 for c in filename): raise invalid('附件名称无效')
    try: mime = await asyncio.to_thread(_validate_content,filename,file.content_type,content)
    except Exception: raise invalid('仅支持内容有效的 PDF、PNG、JPEG 文件') from None
    digest = hashlib.sha256(content).hexdigest()
    scan = await file_scanner.scan_bytes(content)
    scan = {'ERROR':'FAILED','INFECTED':'REJECTED'}.get(scan,scan)
    if scan not in {'CLEAN','PENDING','FAILED','REJECTED'}: scan='FAILED'
    row = OALeaveAttachment(id=str(uuid4()),tenant_id=actor.tenant_id,leave_id=leave_id,uploaded_by=actor.user_id,
        filename=filename,mime_type=mime,size=len(content),sha256=digest,storage_key=uuid4().hex,scan_status=scan)
    path = storage_path(row)
    def store():
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream: stream.write(content)
    await asyncio.to_thread(store)
    async def save(operation):
        _,current = await leaves.applicant_access(db,actor,leave_id,write=True,lock=True)
        leaves.check_editable(current,expected_revision)
        if len(current.fields.get('attachment_ids',[]))>=20: raise invalid('每项申请最多 20 个附件')
        db.add(row)
        current.fields={**current.fields,'attachment_ids':[*current.fields.get('attachment_ids',[]),row.id]}
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=dict(attachment=metadata(row),revision=current.revision))
    try:
        outcome = await run_command(db,actor,OACommand(kind='attachment.upload',target_id=leave_id,target_version=str(expected_revision),
            operation_id=operation_id,payload=dict(filename=filename,mime=mime,size=len(content),sha256=digest,expected_revision=expected_revision),
            resource='leave',target=await leaves.target_for(db,actor,leave),applicant_id=leave.applicant_id),save)
    except Exception:
        await asyncio.to_thread(path.unlink,missing_ok=True)
        raise
    if outcome.replayed: await asyncio.to_thread(path.unlink,missing_ok=True)
    return outcome


async def rescan(db,actor,leave_id,attachment_id,*,operation_id,expected_revision):
    actor,leave = await leaves.applicant_access(db,actor,leave_id,write=True)
    row = (await refs(db,actor,leave_id,[attachment_id]))[0]
    try:
        content = await asyncio.to_thread(read_verified,row)
        scan = await file_scanner.scan_bytes(content)
    except OSError: scan='ERROR'
    scan = {'ERROR':'FAILED','INFECTED':'REJECTED'}.get(scan,scan)
    async def update(operation):
        _,current = await leaves.applicant_access(db,actor,leave_id,write=True,lock=True)
        leaves.check_editable(current,expected_revision)
        from ..models.oa_leave import OALeaveVersion
        versions = (await db.scalars(select(OALeaveVersion).where(OALeaveVersion.tenant_id==actor.tenant_id,OALeaveVersion.leave_id==leave_id))).all()
        if any(any(item['id']==attachment_id for item in version.attachments) for version in versions):
            raise invalid('已提交附件不能重新扫描覆盖，请重新上传')
        row.scan_status=scan if scan in {'CLEAN','PENDING','FAILED','REJECTED'} else 'FAILED'
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=dict(attachment=metadata(row),revision=current.revision))
    return await run_command(db,actor,OACommand(kind='attachment.rescan',target_id=attachment_id,target_version=str(expected_revision),
        operation_id=operation_id,payload=dict(expected_revision=expected_revision),resource='leave',target=await leaves.target_for(db,actor,leave),
        applicant_id=leave.applicant_id),update)


async def download(db,actor,leave_id,attachment_id):
    actor,leave = await leaves.applicant_access(db,actor,leave_id)
    row = (await refs(db,actor,leave_id,[attachment_id]))[0]
    from ..models.oa_leave import OALeaveVersion
    versions = (await db.scalars(select(OALeaveVersion).where(OALeaveVersion.tenant_id==actor.tenant_id,OALeaveVersion.leave_id==leave_id))).all()
    allowed = set(leave.fields.get('attachment_ids',[]))|{item['id'] for version in versions for item in version.attachments}
    if row.id not in allowed or row.scan_status!='CLEAN': raise invalid('附件未引用或未通过安全扫描')
    try: content=await asyncio.to_thread(read_verified,row)
    except OSError: raise invalid('附件缺失或完整性校验失败') from None
    await leaves.applicant_access(db,actor,leave_id)
    return row,content
