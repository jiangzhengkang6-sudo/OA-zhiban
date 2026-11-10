"""
OA 智能体管理系统 - FastAPI 应用入口。

负责应用生命周期管理（建表、启动后台任务）、中间件注册、路由挂载与全局异常处理。
运行时使用 ``uvicorn app.main:app`` 启动。
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .api.routers import (
    auth,
    assistant_v2,
    organization,
    oa_workflows,
    oa_leaves,
    oa_reimbursements,
    oa_tickets,
    oa_notifications,
    oa_announcements,
    oa_delegations,
    oa_work_items,
    oa_balances,
    oa_approvals,
    oa_administration,
    approvals,
    audit,
    audit_export,
    operations,
    readiness,
    interrupts,
    knowledge,
    meetings,
    meeting_events,
    meeting_transcriptions,
    documents,
    emails,
    public_mail,
    work_tasks,
    reports,
    contracts,
    leaves,
    policies,
    support,
    tasks,
    threads,
    tickets,
)
from .core.config import get_settings
from .core.context import get_trace_id
from .core.enums import ErrorCode
from .core.errors import AppException
from .db.migrations import assert_schema_current, validate_runtime_configuration
from .db.session import engine
from .graph.graph_service import runtime
from .middleware.auth import AuthMiddleware
from .middleware.trace import TraceMiddleware
from .schemas.common import ApiResponse
from .services.scheduler import run_scheduler, run_notification_scheduler
from . import models  # noqa: F401  # 确保所有模型注册到 Base.metadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oa-agent")
_settings = get_settings()


async def close_scheduler(task, stop_event, timeout=5.0):
    stop_event.set()
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        logger.info('后台扫描未及时退出，取消本次扫描并回滚未提交事务')
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：建表、初始化 LangGraph、启动调度器、释放引擎。

    Args:
        app: FastAPI 应用实例。
    """
    validate_runtime_configuration(_settings)
    # Startup validates only. Schema upgrades are explicit Alembic operations.
    async with engine.begin() as conn:
        await conn.run_sync(assert_schema_current)
    logger.info("数据库表结构与扩展已就绪")

    # 初始化 LangGraph（Checkpointer + 图编译）
    runtime_initialized = False
    if _settings.ai_enabled:
        await runtime.initialize()
        runtime_initialized = True

    # 启动超时催办/升级调度器
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(run_scheduler(stop_event))
    notification_task = asyncio.create_task(run_notification_scheduler(stop_event))
    from .services.meeting_transcription_service import run as run_transcriptions
    transcription_task = asyncio.create_task(run_transcriptions(stop_event))
    from .ops.operational_errors import install
    error_handler = install(_settings)

    try:
        yield
    finally:
        logging.getLogger().removeHandler(error_handler)
        error_handler.close()
        await asyncio.gather(close_scheduler(scheduler_task, stop_event),close_scheduler(notification_task,stop_event),
                             close_scheduler(transcription_task,stop_event))
        if runtime_initialized:
            await runtime.close()
        await engine.dispose()


app = FastAPI(
    title=_settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

# 中间件（顺序：trace -> auth -> cors）
app.add_middleware(TraceMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.auth_allowed_origins if _settings.auth_provider == 'builtin' else ['*'],
    allow_credentials=_settings.auth_provider == 'builtin',
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    detail = [{'loc':list(e['loc']), 'type':e['type'], 'msg':e['msg']} for e in exc.errors()]
    return JSONResponse(status_code=422, content={'code': ErrorCode.BAD_REQUEST.value, 'message': '请求参数不符合要求', 'data': None, 'detail':detail, 'trace_id': get_trace_id()})


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """统一业务异常处理器。

    Args:
        request: HTTP 请求。
        exc: 业务异常。

    Returns:
        JSONResponse: 统一错误结构。
    """
    return JSONResponse(
        status_code=exc.http_status,
        content=ApiResponse(
            code=exc.code.value,
            message=exc.message,
            trace_id=get_trace_id(),
            request_id=get_trace_id(),
            data=exc.detail,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底未处理异常处理器（记录日志，返回 500）。

    Args:
        request: HTTP 请求。
        exc: 未处理异常。

    Returns:
        JSONResponse: 统一 500 结构。
    """
    # Exception messages/traceback source can contain credentials or request bodies.
    import traceback
    frames = traceback.extract_tb(exc.__traceback__)
    locations = [(frame.name, frame.lineno) for frame in frames[-8:]]
    logger.error("未处理异常；类型=%s；trace_id=%s；调用位置=%s",
                 type(exc).__name__, get_trace_id(), locations)
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            code=ErrorCode.INTERNAL_ERROR.value,
            message="服务内部错误",
            trace_id=get_trace_id(),
            request_id=get_trace_id(),
        ).model_dump(),
    )


# 路由挂载
app.include_router(auth.router, prefix=_settings.api_prefix)
app.include_router(assistant_v2.router, prefix=_settings.api_prefix)
app.include_router(organization.router, prefix=_settings.api_prefix)
app.include_router(oa_workflows.router, prefix=_settings.api_prefix)
app.include_router(oa_leaves.router, prefix=_settings.api_prefix)
app.include_router(oa_reimbursements.router, prefix=_settings.api_prefix)
app.include_router(oa_tickets.router, prefix=_settings.api_prefix)
app.include_router(oa_notifications.router, prefix=_settings.api_prefix)
app.include_router(oa_announcements.router, prefix=_settings.api_prefix)
app.include_router(oa_delegations.router, prefix=_settings.api_prefix)
app.include_router(oa_work_items.router, prefix=_settings.api_prefix)
app.include_router(oa_balances.router, prefix=_settings.api_prefix)
app.include_router(oa_approvals.router, prefix=_settings.api_prefix)
app.include_router(oa_administration.router, prefix=_settings.api_prefix)
app.include_router(threads.router, prefix=_settings.api_prefix)
app.include_router(interrupts.router, prefix=_settings.api_prefix)
app.include_router(approvals.router, prefix=_settings.api_prefix)
app.include_router(tickets.router, prefix=_settings.api_prefix)
app.include_router(tasks.router, prefix=_settings.api_prefix)
app.include_router(leaves.router, prefix=_settings.api_prefix)
app.include_router(audit.router, prefix=_settings.api_prefix)
app.include_router(audit_export.router, prefix=_settings.api_prefix)
app.include_router(operations.router, prefix=_settings.api_prefix)
app.include_router(readiness.router, prefix=_settings.api_prefix)
app.include_router(policies.router, prefix=_settings.api_prefix)
app.include_router(policies.version_router, prefix=_settings.api_prefix)
app.include_router(knowledge.router, prefix=_settings.api_prefix)
app.include_router(meetings.router, prefix=_settings.api_prefix)
app.include_router(meeting_events.router, prefix=_settings.api_prefix)
app.include_router(meeting_transcriptions.router, prefix=_settings.api_prefix)
app.include_router(documents.router, prefix=_settings.api_prefix)
app.include_router(emails.router, prefix=_settings.api_prefix)
app.include_router(public_mail.router, prefix=_settings.api_prefix)
app.include_router(work_tasks.router, prefix=_settings.api_prefix)
app.include_router(reports.router, prefix=_settings.api_prefix)
app.include_router(contracts.router, prefix=_settings.api_prefix)
app.include_router(support.router, prefix=_settings.api_prefix)


@app.get("/healthz")
async def healthz():
    """健康检查接口。

    Returns:
        dict: 健康状态。
    """
    return {"status": "ok", "trace_id": get_trace_id()}
