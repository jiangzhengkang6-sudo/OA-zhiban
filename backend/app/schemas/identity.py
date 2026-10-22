from pydantic import BaseModel, Field, SecretStr


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    current_password: SecretStr
    new_password: SecretStr = Field(min_length=12, max_length=1024)


class PermissionView(BaseModel):
    resource: str
    action: str
    scope: str


class CurrentUserView(BaseModel):
    user_id: str
    display_name: str
    roles: list[str]
    depts: list[str]
    permissions: list[PermissionView]


class AccessGrant(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    user: CurrentUserView
