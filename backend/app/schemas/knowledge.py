"""
OA 智能体管理系统 - 知识库管理请求/响应模型。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeImportRequest(BaseModel):
    """知识文档导入请求（MVP 以文本内容导入为主）。

    Attributes:
        title: 文档标题。
        content: 文档正文。
        format: 源格式（md/html/pdf）。
        permission_tags: 权限标签。
        owner_id: 责任人。
        effective_at: 生效时间。
        expire_at: 失效时间。
    """

    title: str
    content: str
    format: str = "md"
    permission_tags: list[str] = Field(default_factory=list)
    owner_id: str = "u_admin_001"
    effective_at: Optional[datetime] = None
    expire_at: Optional[datetime] = None


class KnowledgeDocumentOut(BaseModel):
    """知识文档响应。

    Attributes:
        id: 文档 ID。
        title: 标题。
        version: 版本。
        status: 状态。
        format: 格式。
        permission_tags: 权限标签。
        effective_at: 生效时间。
        expire_at: 失效时间。
        owner_id: 责任人。
        created_at: 创建时间。
    """

    id: str
    title: str
    version: int
    status: str
    format: str
    permission_tags: list[str]
    effective_at: Optional[datetime] = None
    expire_at: Optional[datetime] = None
    owner_id: Optional[str] = None
    created_at: Optional[datetime] = None


class KnowledgeStatusRequest(BaseModel):
    """文档状态变更请求。

    Attributes:
        status: 目标状态（published/offline/expired）。
    """

    status: str