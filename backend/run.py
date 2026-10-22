"""
OA 智能体管理系统 - 后端启动入口脚本。

LangGraph 的 psycopg 异步 Checkpointer 在 Windows 的 ProactorEventLoop 下不可用，
而 uvicorn 0.52 在 win32 + 非子进程模式下会强制选择 ProactorEventLoop。因此本脚本
手动创建兼容的 SelectorEventLoop 并运行 uvicorn Server，替代 ``python -m uvicorn``。
"""

import asyncio
import os
import sys

import uvicorn


def _build_server() -> uvicorn.Server:
    """构建 uvicorn Server 实例。

    Returns:
        uvicorn.Server: 配置好的服务器实例。
    """
    config = uvicorn.Config("app.main:app", host="127.0.0.1",
                            port=int(os.environ.get("OA_BACKEND_PORT", "8001")))
    return uvicorn.Server(config)


def main() -> None:
    """手动创建 SelectorEventLoop 并运行服务器。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    server = _build_server()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
