"""
OA 智能体管理系统 - 请假预检接口路由。

提供独立的预检入口（供 OA 提交请假单后调用）：
    POST /api/approvals/{business_id}/precheck
预检为确定性规则，复用请假工具，不调用模型。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...adapters.factory import get_adapter
from ...core.errors import AppException, ErrorCode
from ...db.session import get_db
from ...schemas.approval import PrecheckRequest, PrecheckResponse
from ...schemas.common import ok
from ...tools import leave_tools
from ..deps import get_current_user
from ...services.approval_service import reconcile_final_write, validate_safe_retry
from ...repositories import thread_repo
from ...core.errors import not_found
from uuid import UUID
from ...graph.graph_service import extract_interrupt, runtime
from ...services import audit_service
from ...core.enums import AuditAction

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/threads/{thread_id}/reconcile")
async def reconcile_approval(thread_id: UUID, session: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user)):
    thread = await thread_repo.get_thread(session, thread_id)
    if thread is None or thread.tenant_id != user.tenant_id or thread.scene != "leave":
        raise not_found("请假任务不存在")
    status = await reconcile_final_write(session, thread, user)
    await session.commit()
    if runtime.ready:
        try:
            snapshot = await runtime.get_state(thread.id)
            if getattr(snapshot, "next", None):
                await runtime.invoke(thread.id, None)
            updated = await runtime.get_state(thread.id)
            pending = extract_interrupt(updated)
            if status == 'WAITING_HUMAN':
                from ...services.interrupt_service import map_next_action
                status = 'WAITING_HUMAN' if pending else map_next_action(updated.values.get('next_action'))
                if status not in {'WAITING_HUMAN', 'NEEDS_FIX'}:
                    raise RuntimeError('编辑核对后预检或当前审批节点尚未恢复')
            elif getattr(updated, "next", None):
                raise RuntimeError("审批图仍停在未完成节点")
            await thread_repo.update_thread_status(session, thread, status,
                current_interrupt_id=pending[0] if pending else None, error_code=None, error_msg=None)
            await session.commit()
        except Exception as exc:
            import logging
            logging.getLogger('oa-agent').warning('Checkpoint reconciliation failed: %s', exc)
            await audit_service.audit(session, AuditAction.ERROR_OCCURRED.value,
                thread_id=thread.id, business_id=thread.business_id, actor_id=user.user_id,
                error_code=ErrorCode.DEPENDENCY_FAILED.value,
                input_summary={"step": "checkpoint_reconcile"})
            await session.commit()
            raise AppException(ErrorCode.DEPENDENCY_FAILED,
                               "OA 结果已核对但编排尚未对齐，请联系管理员核对", http_status=502) from exc
    return ok({"thread_id": str(thread.id), "status": status})


@router.post("/threads/{thread_id}/retry-write")
async def retry_unstarted_approval(thread_id: UUID, session: AsyncSession = Depends(get_db),
                                   user=Depends(get_current_user)):
    thread = await thread_repo.get_thread(session, thread_id)
    if thread is None or thread.tenant_id != user.tenant_id or thread.scene != "leave":
        raise not_found("请假任务不存在")
    await validate_safe_retry(session, thread, user)
    snapshot = await runtime.get_state(thread.id)
    if not getattr(snapshot, "next", None):
        raise AppException(ErrorCode.INVALID_STATE, "未找到可安全恢复的审批检查点", http_status=409)
    try:
        result = await runtime.invoke(thread.id, None)
        if result.get("next_action") != "approved":
            raise RuntimeError("审批重试未完成权威写入")
    except Exception as exc:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, "审批尚未恢复，请核对依赖与原请求状态", http_status=502) from exc
    await thread_repo.update_thread_status(session, thread, "APPROVED",
        current_interrupt_id=None, error_code=None, error_msg=None)
    await session.commit()
    return ok({"thread_id": str(thread.id), "status": "APPROVED"})


@router.post("/{business_id}/precheck")
async def precheck(
    business_id: str,
    payload: PrecheckRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """执行请假材料预检。

    Args:
        business_id: 业务单据号。
        payload: 预检请求（含 retry）。
        session: 数据库会话。
        user: 当前用户。

    Returns:
        ApiResponse: 预检结果。
    """
    adapter = get_adapter()
    try:
        case = adapter.get_leave_case(business_id)
    except TimeoutError:
        raise AppException(
            ErrorCode.DEPENDENCY_FAILED, "OA 依赖超时，预检暂停", http_status=502
        )

    if case is None:
        raise AppException(ErrorCode.NOT_FOUND, "请假单不存在", http_status=404)
    if case.user_id != user.user_id:
        raise AppException(ErrorCode.FORBIDDEN, "仅申请人本人可独立发起预检", http_status=403)

    results = await leave_tools.validate_leave_form(adapter, case)
    days = leave_tools.compute_days(case)
    balance = adapter.get_leave_balance(case.user_id, case.leave_type).model_dump()
    results.append(leave_tools.check_balance(balance, case.leave_type, days))
    results.append(leave_tools.check_conflict(case))

    passed = all(r["result"] == "pass" for r in results)
    rule_version = adapter.get_field_dict().get("rule_version", "v1")
    return ok(
        PrecheckResponse(
            business_id=business_id,
            precheck_result=results,
            passed=passed,
            status="pass" if passed else "needs_fix",
            rule_version=rule_version,
        )
    )
