from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class DepartmentInput(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    parent_id: str | None = None
    enabled: bool = True


class PositionInput(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    enabled: bool = True


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    display_name: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    password: SecretStr = Field(min_length=12, max_length=1024)
    department_id: str | None = None
    position_id: str | None = None
    manager_id: str | None = None
    role_ids: list[str] | None = None


class UserUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    display_name: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    status: Literal['active', 'disabled'] = 'active'
    department_id: str | None = None
    position_id: str | None = None
    manager_id: str | None = None
    role_ids: list[str] = Field(default_factory=list, max_length=50)


class ResetPassword(BaseModel):
    password: SecretStr = Field(min_length=12, max_length=1024)


class MemberChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['active', 'disabled'] | None = None
    department_id: str | None = None
    position_id: str | None = None
    manager_id: str | None = None
    role_ids: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode='after')
    def nonempty_changes(self):
        if not self.model_fields_set or ('status' in self.model_fields_set and self.status is None) or ('role_ids' in self.model_fields_set and self.role_ids is None):
            raise ValueError('请选择有效的批量调整项')
        return self


class MemberVersion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)


class MemberBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: str = Field(min_length=1, max_length=128)
    members: list[MemberVersion] = Field(min_length=1, max_length=100)
    changes: MemberChanges
    reason: str = Field(min_length=1, max_length=500, pattern=r'.*\S.*')

    @model_validator(mode='after')
    def unique_members(self):
        if len({m.user_id for m in self.members}) != len(self.members):
            raise ValueError('成员不能重复')
        return self


class HandoffCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    kind: Literal['workflow', 'ticket', 'work_task', 'ticket_rule', 'reporting_line']
    item_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)
    target_user_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500, pattern=r'.*\S.*')
    risk_acknowledged: bool = False


class HandoffComplete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500, pattern=r'.*\S.*')


class PermissionInput(BaseModel):
    resource: str = Field(min_length=1, max_length=64)
    action: Literal['read', 'write']
    scope: Literal['self', 'department']


class RoleInput(BaseModel):
    code: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    name: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    permissions: list[PermissionInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def readable_writes(self):
        for permission in self.permissions:
            if permission.action == 'write' and not any(
                p.resource == permission.resource and p.action == 'read'
                and (p.scope == 'department' or p.scope == permission.scope)
                for p in self.permissions
            ):
                raise ValueError('写入权限必须同时配置相同或更大范围的读取权限')
        return self
