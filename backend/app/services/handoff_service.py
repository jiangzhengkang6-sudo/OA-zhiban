"""人工交接队列服务。"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.handoff_snapshot import HandoffSnapshot
from ..models.human_queue_item import HumanQueueItem


def redact_context(context: dict[str, Any]) -> dict[str, Any]:
    """只保留人工处理所需字段，避免把密钥/令牌带入交接包。"""
    blocked = {"authorization", "api_key", "token", "password", "secret"}

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k.lower() not in blocked}
        if isinstance(value, list):
            return [clean(v) for v in value[-20:]]
        if isinstance(value, str):
            return value[:4000]
        return value

    return clean(context)


async def ensure_handoff(
    session: AsyncSession,
    *,
    tenant_id: str,
    thread_id: UUID,
    user_id: str,
    scene: str,
    reason_code: str,
    context: dict[str, Any],
) -> HumanQueueItem:
    """按会话和原因幂等创建人工队列项及不可覆盖快照。"""
    existing = (await session.scalars(select(HumanQueueItem).where(
        HumanQueueItem.thread_id == thread_id,
        HumanQueueItem.reason_code == reason_code,
        HumanQueueItem.status == "OPEN",
    ).limit(1))).one_or_none()
    if existing:
        return existing
    item = HumanQueueItem(tenant_id=tenant_id, thread_id=thread_id, user_id=user_id,
                          scene=scene, reason_code=reason_code,
                          context_summary=str(context.get("summary", ""))[:4000])
    session.add(item)
    await session.flush()
    payload = redact_context({"thread_id": str(thread_id), "scene": scene,
                              "reason_code": reason_code, **context})
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                       default=str).encode()).hexdigest()
    session.add(HandoffSnapshot(queue_item_id=item.id, tenant_id=tenant_id,
                                thread_id=thread_id, payload=payload, payload_hash=digest))
    await session.flush()
    return item

