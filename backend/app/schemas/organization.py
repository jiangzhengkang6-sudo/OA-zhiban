from typing import Literal
from pydantic import BaseModel, Field, SecretStr, model_validator


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
    display_name: str = Field(min_length=1, max_length=128, pattern=r'.*\S.*')
    status: Literal['active', 'disabled'] = 'active'
    department_id: str | None = None
    position_id: str | None = None
    manager_id: str | None = None
    role_ids: list[str] = Field(default_factory=list, max_length=50)


class ResetPassword(BaseModel):
    password: SecretStr = Field(min_length=12, max_length=1024)


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
