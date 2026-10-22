"""
OA 智能体管理系统 - 知识检索工具。

提供 search_knowledge 工具：在权限过滤前提下检索知识库，返回带来源与相似度的切片。
检索失败或未命中时返回空列表（由节点转人工兜底，不猜测）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ..services import knowledge_service


async def search_knowledge(
    db: AsyncSession,
    *,
    query: str,
    permission_tags: list[str],
    top_k: int = 5,
) -> list[dict]:
    """权限过滤知识检索（只读）。

    Args:
        db: 数据库会话。
        query: 用户问题。
        permission_tags: 用户可访问的权限标签。
        top_k: 返回条数。

    Returns:
        list[dict]: 命中切片列表（含来源与相似度），未命中时为空列表。
    """
    return await knowledge_service.search(
        db, query=query, permission_tags=permission_tags, top_k=top_k
    )