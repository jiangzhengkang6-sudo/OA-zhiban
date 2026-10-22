"""
OA 智能体管理系统 - LangGraph 运行期封装。

负责 Checkpointer 初始化、图编译、invoke/get_state/resume 的统一封装。全局单例，
供 service 层与 API 层调用。核心约定：agent_thread.id 即 LangGraph config 的 thread_id。
"""

import logging
from typing import Any, Optional
from uuid import UUID

from langgraph.checkpoint.postgres.aio import (
    AsyncConnection,
    AsyncPostgresSaver,
)
from psycopg.rows import dict_row

from ..core.config import get_settings

logger = logging.getLogger("oa-agent")
_settings = get_settings()


class GraphRuntime:
    """LangGraph 图运行期单例。"""

    def __init__(self) -> None:
        """初始化空状态（graph/checkpointer 在 initialize 时配置）。"""
        self._graph = None
        self._checkpointer: Optional[AsyncPostgresSaver] = None
        self._conn: Optional[AsyncConnection] = None

    async def initialize(self) -> None:
        """初始化 Checkpointer 并编译 SuperAgent 图（幂等）。

        Raises:
            RuntimeError: 图编译或 Checkpointer 初始化失败时。
        """
        from ..services.authorization_service import require_ai_enabled
        require_ai_enabled()
        from .superagent import build_superagent

        self._conn = await AsyncConnection.connect(
            _settings.checkpointer_url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        self._checkpointer = AsyncPostgresSaver(conn=self._conn)
        await self._checkpointer.setup()
        self._graph = build_superagent().compile(checkpointer=self._checkpointer)
        logger.info("LangGraph SuperAgent 图已编译并接入 Checkpointer")

    async def close(self) -> None:
        """关闭 Checkpointer 连接。

        Raises:
            不抛出：连接可能已关闭。
        """
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    @property
    def ready(self) -> bool:
        """图是否已就绪。

        Returns:
            bool: 是否完成编译。
        """
        return self._graph is not None

    @staticmethod
    def config(thread_id: UUID | str) -> dict:
        """构造 LangGraph 运行配置（thread_id 即会话主键）。

        Args:
            thread_id: 会话 ID。

        Returns:
            dict: configurable 配置。
        """
        return {"configurable": {"thread_id": str(thread_id)}}

    async def invoke(self, thread_id: UUID | str, input_state: dict | None) -> dict:
        """同步推进图到结束或下一个中断点。

        Args:
            thread_id: 会话 ID。
            input_state: 初始/追加输入状态。

        Returns:
            dict: 运行后的状态值。

        Raises:
            RuntimeError: 图未初始化时。
        """
        self._ensure_ready()
        return await self._graph.ainvoke(input_state, config=self.config(thread_id))

    async def resume(self, thread_id: UUID | str, resume_value: Any) -> dict:
        """从中断点恢复图运行（注入人工决定）。

        Args:
            thread_id: 会话 ID。
            resume_value: 恢复值（人工决定 dict）。

        Returns:
            dict: 恢复运行后的状态值。

        Raises:
            RuntimeError: 图未初始化时。
        """
        from langgraph.types import Command

        self._ensure_ready()
        return await self._graph.ainvoke(
            Command(resume=resume_value), config=self.config(thread_id)
        )

    async def get_state(self, thread_id: UUID | str):
        """读取当前状态快照（含中断信息）。

        Args:
            thread_id: 会话 ID。

        Returns:
            StateSnapshot: 状态快照。
        """
        self._ensure_ready()
        return await self._graph.aget_state(self.config(thread_id))

    async def update_state(self, thread_id: UUID | str, values: dict, *, as_node: str | None = None):
        """Update authoritative meeting review fields without advancing the graph."""
        self._ensure_ready()
        kwargs = {"as_node": as_node} if as_node else {}
        return await self._graph.aupdate_state(self.config(thread_id), values, **kwargs)

    def _ensure_ready(self) -> None:
        """断言图已初始化。

        Raises:
            RuntimeError: 图未初始化时。
        """
        from ..services.authorization_service import require_ai_enabled
        require_ai_enabled()
        if self._graph is None:
            raise RuntimeError("LangGraph 图未初始化，请先调用 initialize()")


# 全局单例
runtime = GraphRuntime()


def extract_interrupt(state_snapshot) -> Optional[tuple[str, Any]]:
    """从状态快照中提取 pending 中断（interrupt_id, payload）。

    Args:
        state_snapshot: get_state 返回的快照。

    Returns:
        Optional[tuple[str, Any]]: (中断 ID, 中断负载)，无中断时为 None。
    """
    tasks = getattr(state_snapshot, "tasks", None) or ()
    for task in tasks:
        interrupts = getattr(task, "interrupts", None) or ()
        for it in interrupts:
            value = getattr(it, "value", None)
            intercept_id = getattr(it, "id", None) or _interrupt_key(value)
            return intercept_id, value
    return None


def _interrupt_key(value: Any) -> str:
    """无显式 interrupt id 时生成稳定 key（payload 中 thread_id 优先）。

    Args:
        value: 中断负载。

    Returns:
        str: 中断标识。
    """
    if isinstance(value, dict) and value.get("thread_id"):
        return str(value["thread_id"])
    return "interrupt"
