"""Private invoice files bound to a reimbursement, with immutable manifests."""
import asyncio
import hashlib
from uuid import uuid4

from sqlalchemy import select
from ..core.config import get_settings
from ..models.oa_reimbursement import OAReimbursementAttachment,OAReimbursementVersion
from ..providers import file_scanner
from .oa_access_service import invalid,revision_conflict
from .oa_command_service import OACommand,CommandOutcome,run_command
from .oa_attachment_service import metadata,storage_path,read_verified
from .leave_attachment_service import _validate_content
from . import oa_reimbursement_service as reimbursements


async def refs(db,actor,reimbursement_id,ids):
    rows=(await db.scalars(select(OAReimbursementAttachment).where(OAReimbursementAttachment.tenant_id==actor.tenant_id,
        OAReimbursementAttachment.reimbursement_id==reimbursement_id,OAReimbursementAttachment.id.in_(ids)))).all() if ids else []
    indexed={row.id:row for row in rows}
    if any(key not in indexed for key in ids): raise invalid('发票引用不存在或不属于本报销单')
    return [indexed[key] for key in ids]


async def preflight(db,actor,reimbursement_id,ids):
    actor,_=await reimbursements.applicant_access(db,actor,reimbursement_id,write=True)
    if not ids: raise invalid('请至少上传一张通过扫描的发票')
    rows=await refs(db,actor,reimbursement_id,ids)
    for row in rows:
        if row.scan_status!='CLEAN': raise invalid('发票尚未通过安全扫描')
        try: await asyncio.to_thread(read_verified,row)
        except OSError: raise invalid('发票缺失或完整性校验失败') from None
    return [metadata(row) for row in rows]


async def verify_manifest(db,actor,reimbursement_id,manifest):
    rows=await refs(db,actor,reimbursement_id,[item['id'] for item in manifest])
    if not rows or [metadata(row) for row in rows]!=manifest: raise revision_conflict()


async def upload(db,actor,reimbursement_id,file,*,operation_id,expected_revision):
    actor,row=await reimbursements.applicant_access(db,actor,reimbursement_id,write=True)
    content=await file.read(get_settings().attachment_max_bytes+1)
    if not content or len(content)>get_settings().attachment_max_bytes: raise invalid('发票为空或超过大小上限')
    filename=(file.filename or '').replace('\\','/').rsplit('/',1)[-1]
    if not filename or len(filename)>255 or any(ord(c)<32 for c in filename): raise invalid('发票文件名无效')
    try: mime=await asyncio.to_thread(_validate_content,filename,file.content_type,content)
    except Exception: raise invalid('仅支持内容有效的 PDF、PNG、JPEG 发票文件') from None
    digest=hashlib.sha256(content).hexdigest()
    scan=await file_scanner.scan_bytes(content)
    scan={'ERROR':'FAILED','INFECTED':'REJECTED'}.get(scan,scan)
    if scan not in {'CLEAN','PENDING','FAILED','REJECTED'}: scan='FAILED'
    attachment=OAReimbursementAttachment(id=str(uuid4()),tenant_id=actor.tenant_id,reimbursement_id=reimbursement_id,
        uploaded_by=actor.user_id,filename=filename,mime_type=mime,size=len(content),sha256=digest,storage_key=uuid4().hex,scan_status=scan)
    path=storage_path(attachment)
    def store():
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream: stream.write(content)
    await asyncio.to_thread(store)
    async def save(operation):
        _,current=await reimbursements.applicant_access(db,actor,reimbursement_id,write=True,lock=True)
        reimbursements.check_editable(current,expected_revision)
        if len(current.fields.get('attachment_ids',[]))>=20: raise invalid('每项报销最多 20 个发票附件')
        db.add(attachment)
        current.fields={**current.fields,'attachment_ids':[*current.fields.get('attachment_ids',[]),attachment.id]}
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=dict(attachment=metadata(attachment),revision=current.revision))
    try:
        outcome=await run_command(db,actor,OACommand(kind='reimbursement.attachment.upload',target_id=reimbursement_id,target_version=str(expected_revision),
            operation_id=operation_id,payload=dict(filename=filename,mime=mime,size=len(content),sha256=digest,expected_revision=expected_revision),
            resource='reimbursement',target=await reimbursements.target_for(db,actor,row),applicant_id=row.applicant_id),save)
    except Exception:
        await asyncio.to_thread(path.unlink,missing_ok=True)
        raise
    if outcome.replayed: await asyncio.to_thread(path.unlink,missing_ok=True)
    return outcome


async def rescan(db,actor,reimbursement_id,attachment_id,*,operation_id,expected_revision):
    actor,row=await reimbursements.applicant_access(db,actor,reimbursement_id,write=True)
    attachment=(await refs(db,actor,reimbursement_id,[attachment_id]))[0]
    try:
        content=await asyncio.to_thread(read_verified,attachment)
        scan=await file_scanner.scan_bytes(content)
    except OSError: scan='ERROR'
    scan={'ERROR':'FAILED','INFECTED':'REJECTED'}.get(scan,scan)
    async def update(operation):
        _,current=await reimbursements.applicant_access(db,actor,reimbursement_id,write=True,lock=True)
        reimbursements.check_editable(current,expected_revision)
        versions=(await db.scalars(select(OAReimbursementVersion).where(OAReimbursementVersion.tenant_id==actor.tenant_id,
            OAReimbursementVersion.reimbursement_id==reimbursement_id))).all()
        if any(any(item['id']==attachment_id for item in version.attachments) for version in versions):
            raise invalid('已提交发票不可覆盖扫描结果，请重新上传')
        attachment.scan_status=scan if scan in {'CLEAN','PENDING','FAILED','REJECTED'} else 'FAILED'
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=dict(attachment=metadata(attachment),revision=current.revision))
    return await run_command(db,actor,OACommand(kind='reimbursement.attachment.rescan',target_id=attachment_id,target_version=str(expected_revision),
        operation_id=operation_id,payload=dict(expected_revision=expected_revision),resource='reimbursement',
        target=await reimbursements.target_for(db,actor,row),applicant_id=row.applicant_id),update)


async def download(db,actor,reimbursement_id,attachment_id):
    actor,row=await reimbursements.applicant_access(db,actor,reimbursement_id)
    attachment=(await refs(db,actor,reimbursement_id,[attachment_id]))[0]
    versions=(await db.scalars(select(OAReimbursementVersion).where(OAReimbursementVersion.tenant_id==actor.tenant_id,
        OAReimbursementVersion.reimbursement_id==reimbursement_id))).all()
    allowed=set(row.fields.get('attachment_ids',[]))|{item['id'] for version in versions for item in version.attachments}
    if attachment.id not in allowed or attachment.scan_status!='CLEAN': raise invalid('发票未引用或尚未通过扫描')
    try: content=await asyncio.to_thread(read_verified,attachment)
    except OSError: raise invalid('发票缺失或完整性校验失败') from None
    await reimbursements.applicant_access(db,actor,reimbursement_id)
    return attachment,content
