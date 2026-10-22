"""
OA 智能体管理系统 - 应用包初始化。

在 Windows 上设置 SelectorEventLoop 策略：LangGraph 的 psycopg 异步 Checkpointer
在 Windows 的 ProactorEventLoop 下不可用，需在事件循环创建前切换到
WindowsSelectorEventLoopPolicy（asyncpg 同样兼容该循环）。
"""

import asyncio
import sys


def _setup_event_loop_policy() -> None:
    """为 Windows 设置兼容的事件循环策略。

    Raises:
        不抛出：若策略切换失败（如循环已在运行）则保持默认。
    """
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass


_setup_event_loop_policy()