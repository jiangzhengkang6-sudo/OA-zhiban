"""Resolve explicitly typed workflow subjects in the caller's transaction."""
from dataclasses import dataclass
from typing import Literal
from sqlalchemy import select

from ..models.oa_leave import OALeave, OALeaveVersion
from ..models.oa_reimbursement import OAReimbursement, OAReimbursementVersion
from .oa_access_service import tenant_row, denied, invalid


@dataclass(frozen=True)
class OAWorkflowSubject:
    scene: Literal['leave','reimbursement']
    row: OALeave | OAReimbursement
    version: OALeaveVersion | OAReimbursementVersion

    @property
    def object_id(self): return self.row.id
    @property
    def version_id(self): return self.version.id
    @property
    def owner_id(self): return self.row.applicant_id
    @property
    def department_id(self): return self.row.department_id
    @property
    def submission_version(self): return self.version.version
    @property
    def state(self): return self.row.state
    @property
    def fields(self): return self.version.fields
    @property
    def attachment_manifest(self): return self.version.attachments


def subject_scene(row):
    if isinstance(row,OALeave): return 'leave'
    if isinstance(row,OAReimbursement): return 'reimbursement'
    raise invalid('未知流程业务类型')


def subject_models(scene):
    if scene=='leave': return OALeave,OALeaveVersion,'leave_id','leave_version_id'
    if scene=='reimbursement': return OAReimbursement,OAReimbursementVersion,'reimbursement_id','reimbursement_version_id'
    raise invalid('未知流程业务类型')


async def resolve_subject(db,actor,instance,*,lock=False):
    if instance.tenant_id!=actor.tenant_id: raise denied()
    model,version_model,key,association=subject_models(instance.scene)
    version_id=getattr(instance,association)
    other=instance.reimbursement_version_id if instance.scene=='leave' else instance.leave_version_id
    if not version_id or other: raise invalid('流程业务关联异常')
    version=await tenant_row(db,version_model,actor,version_id)
    row=await tenant_row(db,model,actor,getattr(version,key),lock=lock)
    return OAWorkflowSubject(instance.scene,row,version)


async def attachment_refs(db,actor,row,ids):
    if subject_scene(row)=='leave':
        from .oa_attachment_service import refs
        return await refs(db,actor,row.id,ids)
    from .oa_reimbursement_attachment_service import refs
    return await refs(db,actor,row.id,ids)
